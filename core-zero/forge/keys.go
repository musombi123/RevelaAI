// Package forge implements the local API-key request workflow. Keys are pending until human approval.
package forge

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

type KeyRequest struct {
	ID string `json:"id"`
	Name string `json:"name"`
	Email string `json:"email"`
	RepositoryURL string `json:"repository_url,omitempty"`
	Reason string `json:"reason"`
	Scopes []string `json:"scopes"`
	Status string `json:"status"`
	CreatedAt time.Time `json:"created_at"`
	DecisionAt *time.Time `json:"decision_at,omitempty"`
	DecisionBy string `json:"decision_by,omitempty"`
	IssuedKeyID string `json:"issued_key_id,omitempty"`
}
type IssuedKey struct {
	ID string `json:"id"`
	RequestID string `json:"request_id"`
	KeyHash string `json:"key_hash"`
	Scopes []string `json:"scopes"`
	Status string `json:"status"`
	CreatedAt time.Time `json:"created_at"`
	ExpiresAt time.Time `json:"expires_at"`
	RevokedAt *time.Time `json:"revoked_at,omitempty"`
	RevokedBy string `json:"revoked_by,omitempty"`
}
type KeyManager struct { Root string; mu sync.Mutex }
var allowedScopes = map[string]bool{"scan:read":true,"heal:propose":true,"assemble:propose":true,"radar:compare":true,"mind:compile":true,"bridge:propose":true}
func New(root string) *KeyManager { return &KeyManager{Root:root} }
func (m *KeyManager) dirs() error { for _,d := range []string{"state/keys/requests","state/keys/issued"} { if e:=os.MkdirAll(filepath.Join(m.Root,d),0700); e!=nil{return e} }; return nil }
func newID() (string,error) { b:=make([]byte,12); if _,e:=rand.Read(b);e!=nil{return "",e}; return hex.EncodeToString(b),nil }
func keyHash(s string) string { h:=sha256.Sum256([]byte(s)); return hex.EncodeToString(h[:]) }
func write(path string,v any) error { if e:=os.MkdirAll(filepath.Dir(path),0700);e!=nil{return e}; b,e:=json.MarshalIndent(v,"","  "); if e!=nil{return e}; b=append(b,'\n'); tmp:=path+".tmp"; if e=os.WriteFile(tmp,b,0600);e!=nil{return e}; return os.Rename(tmp,path) }
func read(path string,v any) error { b,e:=os.ReadFile(path); if e!=nil{return e}; return json.Unmarshal(b,v) }
func cleanScopes(scopes []string) ([]string,error) { if len(scopes)==0{scopes=[]string{"scan:read"}}; set:=map[string]bool{}; for _,s:=range scopes { s=strings.TrimSpace(s); if !allowedScopes[s]{return nil,fmt.Errorf("scope %q is not requestable",s)}; set[s]=true }; out:=make([]string,0,len(set)); for s:=range set{out=append(out,s)}; sort.Strings(out); return out,nil }
func (m *KeyManager) Request(name,email,repo,reason string,scopes []string) (KeyRequest,error) {
	m.mu.Lock(); defer m.mu.Unlock(); if err:=m.dirs();err!=nil{return KeyRequest{},err}
	name=strings.TrimSpace(name); email=strings.TrimSpace(email); repo=strings.TrimSpace(repo); reason=strings.TrimSpace(reason)
	if len(name)<2 || len(name)>120 || !strings.Contains(email,"@") || len(email)>254 || len(reason)<8 || len(reason)>1200{return KeyRequest{},errors.New("name, valid email and an 8–1200 character reason are required")}
	if repo!="" { u,e:=url.ParseRequestURI(repo); if e!=nil || u.Scheme!="https" || u.Host==""{return KeyRequest{},errors.New("repository_url must be an HTTPS URL")} }
	clean,e:=cleanScopes(scopes); if e!=nil{return KeyRequest{},e}; id,e:=newID(); if e!=nil{return KeyRequest{},e}
	r:=KeyRequest{ID:id,Name:name,Email:email,RepositoryURL:repo,Reason:reason,Scopes:clean,Status:"pending_approval",CreatedAt:time.Now().UTC()}
	if e=write(filepath.Join(m.Root,"state","keys","requests",id+".json"),r);e!=nil{return KeyRequest{},e}; return r,nil
}
func (m *KeyManager) Approve(id,actor string,ttl time.Duration) (KeyRequest,string,error) {
	m.mu.Lock(); defer m.mu.Unlock(); if err:=m.dirs();err!=nil{return KeyRequest{},"",fmt.Errorf("key store unavailable: %w",err)}
	if strings.ContainsAny(id,"/\\\x00") || id==""{return KeyRequest{},"",os.ErrNotExist}
	p:=filepath.Join(m.Root,"state","keys","requests",id+".json"); var r KeyRequest; if e:=read(p,&r);e!=nil{return r,"",e}; if r.Status!="pending_approval"{return r,"",errors.New("request is not pending approval")}
	if ttl<=0{ttl=90*24*time.Hour}; raw:=make([]byte,32); if _,e:=rand.Read(raw);e!=nil{return r,"",e}; secret:="uz0_"+base64.RawURLEncoding.EncodeToString(raw); keyID,e:=newID(); if e!=nil{return r,"",e}
	now:=time.Now().UTC(); k:=IssuedKey{ID:keyID,RequestID:id,KeyHash:keyHash(secret),Scopes:r.Scopes,Status:"active",CreatedAt:now,ExpiresAt:now.Add(ttl)}
	if e=write(filepath.Join(m.Root,"state","keys","issued",keyID+".json"),k);e!=nil{return r,"",e}
	r.Status="approved"; r.IssuedKeyID=keyID; r.DecisionAt=&now; r.DecisionBy=strings.TrimSpace(actor)
	if e=write(p,r);e!=nil{_ = os.Remove(filepath.Join(m.Root,"state","keys","issued",keyID+".json"));return r,"",e}; return r,secret,nil
}
func (m *KeyManager) ListRequests(status string) ([]KeyRequest,error) {
	m.mu.Lock(); defer m.mu.Unlock(); if err:=m.dirs();err!=nil{return nil,err}; entries,err:=os.ReadDir(filepath.Join(m.Root,"state","keys","requests"));if err!=nil{return nil,err};items:=make([]KeyRequest,0,len(entries))
	for _,entry:=range entries { if entry.IsDir()||!strings.HasSuffix(entry.Name(),".json"){continue};var request KeyRequest;if err:=read(filepath.Join(m.Root,"state","keys","requests",entry.Name()),&request);err!=nil{continue};if status==""||request.Status==status{items=append(items,request)} }
	sort.Slice(items,func(i,j int)bool{return items[i].CreatedAt.After(items[j].CreatedAt)});return items,nil
}
func (m *KeyManager) ListIssued(status string) ([]IssuedKey, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if err := m.dirs(); err != nil {
		return nil, err
	}

	entries, err := os.ReadDir(filepath.Join(m.Root, "state", "keys", "issued"))
	if err != nil {
		return nil, err
	}

	now := time.Now().UTC()
	items := make([]IssuedKey, 0, len(entries))
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
			continue
		}
		var key IssuedKey
		if err := read(filepath.Join(m.Root, "state", "keys", "issued", entry.Name()), &key); err != nil {
			continue
		}
		effectiveStatus := key.Status
		if effectiveStatus == "active" && !now.Before(key.ExpiresAt) {
			effectiveStatus = "expired"
		}
		if status != "" && effectiveStatus != status {
			continue
		}
		// Return a copy with the effective status. The caller must explicitly
		// project public fields before exposing this struct over HTTP.
		key.Status = effectiveStatus
		items = append(items, key)
	}
	sort.Slice(items, func(i, j int) bool {
		return items[i].CreatedAt.After(items[j].CreatedAt)
	})
	return items, nil
}

func (m *KeyManager) Revoke(id,actor string) (IssuedKey,error) {
	m.mu.Lock();defer m.mu.Unlock();if err:=m.dirs();err!=nil{return IssuedKey{},err};if strings.ContainsAny(id,"/\\\x00")||id==""{return IssuedKey{},os.ErrNotExist}
	path:=filepath.Join(m.Root,"state","keys","issued",id+".json");var key IssuedKey;if err:=read(path,&key);err!=nil{return key,err};if key.Status!="active"{return key,errors.New("key is not active")};now:=time.Now().UTC();key.Status="revoked";key.RevokedAt=&now;key.RevokedBy=strings.TrimSpace(actor);if err:=write(path,key);err!=nil{return key,err};return key,nil
}
func (m *KeyManager) Validate(secret,scope string) (bool,string) {
	m.mu.Lock();defer m.mu.Unlock();if secret==""||!allowedScopes[scope]{return false,""};entries,e:=os.ReadDir(filepath.Join(m.Root,"state","keys","issued"));if e!=nil{return false,""};want:=keyHash(secret)
	for _,entry:=range entries { if entry.IsDir()||!strings.HasSuffix(entry.Name(),".json"){continue};var k IssuedKey;if read(filepath.Join(m.Root,"state","keys","issued",entry.Name()),&k)!=nil{continue};got,e:=hex.DecodeString(k.KeyHash);expected,e2:=hex.DecodeString(want);if e!=nil||e2!=nil||subtle.ConstantTimeCompare(got,expected)!=1{continue};if k.Status!="active"||time.Now().UTC().After(k.ExpiresAt){return false,k.ID};for _,s:=range k.Scopes{if s==scope{return true,k.ID}};return false,k.ID }
	return false,""
}
