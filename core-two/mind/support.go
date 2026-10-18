package mind

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

func countEndpointUsage(path string)(int,bool){f,err:=os.Open(path);if err!=nil{return 0,false};defer f.Close();scanner:=bufio.NewScanner(f);scanner.Buffer(make([]byte,4096),1<<20);count:=0;for scanner.Scan(){var event map[string]any;if json.Unmarshal(scanner.Bytes(),&event)!=nil{continue};typ,_:=event["type"].(string);if typ=="http_request"||typ=="endpoint_access"||typ=="endpoint_used"{count++}};if scanner.Err()!=nil{return count,false};return count,count>0}
func(s *Service)productionToolCount()int{items,err:=s.One.ListInventions();if err!=nil{return 0};return len(items)}
func(s *Service)coreOneLibraryInventory()map[string]any{root:=filepath.Join(s.OneRoot,"libraries","created");type libraryFile struct{Path string `json:"path"`;SHA256 string `json:"sha256"`;Bytes int `json:"bytes"`};files:=[]libraryFile{};_ = filepath.WalkDir(root,func(path string,entry os.DirEntry,walkErr error)error{if walkErr!=nil{return nil};if entry.IsDir(){return nil};if filepath.Ext(entry.Name())!=".go"&&filepath.Ext(entry.Name())!=".rvx"{return nil};info,err:=entry.Info();if err!=nil||!info.Mode().IsRegular(){return nil};raw,err:=os.ReadFile(path);if err!=nil{return nil};rel,err:=filepath.Rel(s.RepoRoot,path);if err!=nil{return nil};files=append(files,libraryFile{Path:filepath.ToSlash(rel),SHA256:hashString(string(raw)),Bytes:len(raw)});return nil});note:="Existing library sources were inventoried read-only; candidate artifacts remain separate proposals.";if len(files)==0{note="No existing Core-One library source files were present to mutate in this snapshot; candidates are curated proposal templates."};return map[string]any{"root":"core-one/libraries/created","source_files_observed":len(files),"files":files,"source_copied":false,"note":note}}
func(s *Service)recentEvents()[]map[string]any{s.mu.RLock();defer s.mu.RUnlock();start:=0;if len(s.events)>20{start=len(s.events)-20};out:=make([]map[string]any,0,len(s.events)-start);for _,event:=range s.events[start:]{out=append(out,event)};return out}
func nextEvolutionVersion(root string)(string,error){entries,err:=os.ReadDir(root);if err!=nil{return "",err};maxPatch:=-1;for _,e:=range entries{if !e.IsDir(){continue};name:=strings.TrimPrefix(e.Name(),"v");parts:=strings.Split(name,".");if len(parts)!=3||parts[0]!="0"||parts[1]!="1"{continue};n,er:=strconv.Atoi(parts[2]);if er==nil&&n>maxPatch{maxPatch=n}};return fmt.Sprintf("v0.1.%d",maxPatch+1),nil}
func remoteIsLoopback(remote string)bool{host,_,err:=net.SplitHostPort(remote);if err!=nil{host=remote};ip:=net.ParseIP(strings.Trim(host,"[]"));return ip!=nil&&ip.IsLoopback()}
func subtleConstantTimeEqual(a,b string)bool{if len(a)!=len(b){return false};var v byte;for i:=0;i<len(a);i++{v|=a[i]^b[i]};return v==0}
func validName(name string)bool{if name==""||len(name)>64||name=="."||name==".."{return false};for _,r:=range name{if !(r>='a'&&r<='z'||r>='0'&&r<='9'||r=='_'||r=='-'){return false}};return true}
func hashString(s string)string{sum:=sha256.Sum256([]byte(s));return hex.EncodeToString(sum[:])}
func fileExists(path string)bool{info,err:=os.Stat(path);return err==nil&&!info.IsDir()}
func directoryExists(path string)bool{info,err:=os.Stat(path);return err==nil&&info.IsDir()}
func countSourceFiles(root string)int{entries,err:=os.ReadDir(root);if err!=nil{return 0};n:=0;for _,e:=range entries{if !e.IsDir()&&(strings.HasSuffix(e.Name(),".go")||strings.HasSuffix(e.Name(),".rvx")){n++}};return n}
func countLogLines(path,filter string)(int,bool){f,err:=os.Open(path);if err!=nil{return 0,false};defer f.Close();count:=0;scan:=bufio.NewScanner(f);for scan.Scan(){line:=strings.ToLower(scan.Text());if filter==""||containsAny(line,strings.Split(filter,"|")){count++}};return count,true}
func containsAny(s string,terms []string)bool{for _,term:=range terms{if term!=""&&strings.Contains(s,term){return true}};return false}
func numberField(obj map[string]any,keys ...string)(float64,bool){for _,key:=range keys{if value,ok:=obj[key];ok{switch n:=value.(type){case float64:return n,true;case int:return float64(n),true}}};return 0,false}
func average(values []float64)float64{if len(values)==0{return 0};total:=0.0;for _,v:=range values{total+=v};return total/float64(len(values))}
func writeJSONFile(path string,value any,mode os.FileMode)error{raw,err:=json.MarshalIndent(value,"","  ");if err!=nil{return err};return atomicWrite(path,append(raw,'\n'),mode)}
func writeJSON(w http.ResponseWriter,status int,value any){w.Header().Set("Content-Type","application/json; charset=utf-8");w.WriteHeader(status);_ = json.NewEncoder(w).Encode(value)}
func writeAPIError(w http.ResponseWriter,status int,code,message string){writeJSON(w,status,map[string]string{"status":"error","code":code,"message":message})}
func decodeJSON(w http.ResponseWriter,r *http.Request,out any)error{defer r.Body.Close();decoder:=json.NewDecoder(http.MaxBytesReader(w,r.Body,1<<20));decoder.DisallowUnknownFields();if err:=decoder.Decode(out);err!=nil{return err};var extra any;if err:=decoder.Decode(&extra);err!=io.EOF{return errors.New("request body must contain exactly one JSON value")};return nil}
func atomicWrite(path string,data []byte,mode os.FileMode)error{if err:=os.MkdirAll(filepath.Dir(path),0o700);err!=nil{return err};tmp,err:=os.CreateTemp(filepath.Dir(path),".mind-tmp-");if err!=nil{return err};tmpPath:=tmp.Name();ok:=false;defer func(){tmp.Close();if !ok{_ = os.Remove(tmpPath)}}();if err:=tmp.Chmod(mode);err!=nil{return err};if _,err:=tmp.Write(data);err!=nil{return err};if err:=tmp.Sync();err!=nil{return err};if err:=tmp.Close();err!=nil{return err};if err:=os.Rename(tmpPath,path);err!=nil{return err};ok=true;return nil}
func writeNewFile(path string,data []byte,mode os.FileMode)error{if err:=os.MkdirAll(filepath.Dir(path),0o700);err!=nil{return err};f,err:=os.OpenFile(path,os.O_WRONLY|os.O_CREATE|os.O_EXCL,mode);if err!=nil{return err};if _,err=f.Write(data);err!=nil{_ = f.Close();return err};return f.Close()}
