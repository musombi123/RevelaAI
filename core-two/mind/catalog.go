package mind

import (
	"errors"
	"fmt"
	"go/ast"
	"go/importer"
	"go/parser"
	"go/token"
	"go/types"
	"strconv"
	"strings"
)

type candidateSpec struct { ID, Category, Purpose, Source string }
type CandidateEvaluation struct {
	ID string `json:"id"`; Category string `json:"category"`; ImprovementType string `json:"improvement_type"`; BaselineValue float64 `json:"baseline_value"`; CandidateValue float64 `json:"candidate_value"`; ImprovementPct float64 `json:"improvement_percent"`; Passed bool `json:"passed"`; MeasurementSource string `json:"measurement_source"`; Evidence map[string]any `json:"evidence,omitempty"`; Note string `json:"note,omitempty"`
}
const sharedCandidateTest = `package candidate
import "testing"
func TestProposalFixture(t *testing.T) { if err := Validate(); err != nil { t.Fatal(err) } }
`
var candidateCatalog = []candidateSpec{
{ID:"graph-indexed",Category:"graph_traversal",Purpose:"Replace linear visited-node scans with an indexed set for the offline_vault dependency graph.",Source:`package candidate
import "errors"
const CandidateID = "graph-indexed"
type Graph map[string][]string
func Reachable(g Graph,start string)[]string{if start==""{return nil};queue:=[]string{start};seen:=map[string]struct{}{start:{}};out:=make([]string,0,len(g)+1);for head:=0;head<len(queue);head++{n:=queue[head];out=append(out,n);for _,next:=range g[n]{if next==""{continue};if _,ok:=seen[next];ok{continue};seen[next]=struct{}{};queue=append(queue,next)}};return out}
func Validate()error{g:=Graph{"a":{"b","c"},"b":{"c"},"c":{}};got:=Reachable(g,"a");if len(got)!=3||got[0]!="a"||got[1]!="b"||got[2]!="c"{return errors.New("graph traversal output mismatch")};return nil}
`},
{ID:"bom-cost-ranked",Category:"bom_search",Purpose:"Rank supplied offline BOM quotes by verified availability and total quoted cost; no live prices are fetched.",Source:`package candidate
import "errors"
const CandidateID = "bom-cost-ranked"
type Quote struct{Supplier string;UnitCost,TransportCost int64;InStock bool}
func BestQuote(q []Quote)(Quote,bool){var best Quote;found:=false;for _,v:=range q{if !v.InStock||v.UnitCost<0||v.TransportCost<0||v.Supplier==""{continue};if !found||v.UnitCost+v.TransportCost<best.UnitCost+best.TransportCost{best=v;found=true}};return best,found}
func Validate()error{got,ok:=BestQuote([]Quote{{Supplier:"fixture-a",UnitCost:1000,TransportCost:250,InStock:true},{Supplier:"fixture-b",UnitCost:900,TransportCost:100,InStock:true}});if !ok||got.Supplier!="fixture-b"{return errors.New("quote ranking mismatch")};return nil}
`},
{ID:"hardware-guide-structured",Category:"hardware_guide",Purpose:"Produce a clearer fundi-facing guide with prerequisites, parts, numbered steps, verification, and stop conditions.",Source:`package candidate
import("errors";"strings";"strconv")
const CandidateID = "hardware-guide-structured"
func BuildGuide(parts,steps,checks,stop []string)string{var b strings.Builder;b.WriteString("Prerequisites\n");for _,x:=range parts{b.WriteString("- "+x+"\n")};b.WriteString("Steps\n");for i,x:=range steps{b.WriteString(strconv.Itoa(i+1)+". "+x+"\n")};b.WriteString("Verification\n");for _,x:=range checks{b.WriteString("- "+x+"\n")};b.WriteString("Stop conditions\n");for _,x:=range stop{b.WriteString("- "+x+"\n")};return b.String()}
func Validate()error{s:=BuildGuide([]string{"disconnect power"},[]string{"inspect","test"},[]string{"verify"},[]string{"stop if unsure"});for _,v:=range []string{"Prerequisites","Steps","Verification","Stop conditions"}{if !strings.Contains(s,v){return errors.New("required guide section missing")}};return nil}
`},
{ID:"rvx-aead-envelope",Category:"rvx_protection",Purpose:"Stage AES-GCM protection for artifacts using an externally supplied key; never claim absolute uncopyability.",Source:`package candidate
import("crypto/aes";"crypto/cipher";"crypto/rand";"crypto/sha256";"errors";"io")
const CandidateID = "rvx-aead-envelope"
func Seal(key string,plain []byte)([]byte,error){if len(key)<32{return nil,errors.New("key too short")};sum:=sha256.Sum256([]byte(key));block,e:=aes.NewCipher(sum[:]);if e!=nil{return nil,e};g,e:=cipher.NewGCM(block);if e!=nil{return nil,e};nonce:=make([]byte,g.NonceSize());if _,e=io.ReadFull(rand.Reader,nonce);e!=nil{return nil,e};return append(nonce,g.Seal(nil,nonce,plain,[]byte("rvx-aead-v1"))...),nil}
func Open(key string,box []byte)([]byte,error){if len(key)<32{return nil,errors.New("key too short")};sum:=sha256.Sum256([]byte(key));block,e:=aes.NewCipher(sum[:]);if e!=nil{return nil,e};g,e:=cipher.NewGCM(block);if e!=nil{return nil,e};if len(box)<g.NonceSize(){return nil,errors.New("invalid box")};return g.Open(nil,box[:g.NonceSize()],box[g.NonceSize():],[]byte("rvx-aead-v1"))}
func Validate()error{key:="fixture-only-key-not-a-production-secret-012345";box,e:=Seal(key,[]byte("sample"));if e!=nil{return e};plain,e:=Open(key,box);if e!=nil||string(plain)!="sample"{return errors.New("AEAD round trip failed")};box[len(box)-1]^=1;if _,e=Open(key,box);e==nil{return errors.New("tampering was not detected")};return nil}
`},
{ID:"cross-industry-pollination",Category:"pollination",Purpose:"Score reusable capabilities across explicitly named industries without auto-connecting unsafe domains.",Source:`package candidate
import "errors"
const CandidateID = "cross-industry-pollination"
func Shared(a,b []string)[]string{set:=map[string]bool{};for _,x:=range a{if x!=""{set[x]=true}};out:=[]string{};seen:=map[string]bool{};for _,x:=range b{if set[x]&&!seen[x]{out=append(out,x);seen[x]=true}};return out}
func Validate()error{if len(Shared([]string{"offline","audit","offline"},[]string{"audit","offline"}))!=2{return errors.New("cross-domain capability matching failed")};return nil}
`},
{ID:"evidence-hash-dedup",Category:"evidence",Purpose:"Deduplicate repeated research evidence using stable content fingerprints.",Source:`package candidate
import("crypto/sha256";"encoding/hex";"strings")
const CandidateID = "evidence-hash-dedup"
func Deduplicate(items []string)[]string{seen:=map[string]bool{};out:=[]string{};for _,x:=range items{x=strings.TrimSpace(x);if x==""{continue};h:=sha256.Sum256([]byte(x));k:=hex.EncodeToString(h[:]);if !seen[k]{seen[k]=true;out=append(out,x)}};return out}
func Validate()error{got:=Deduplicate([]string{"alpha","alpha"," beta ",""});if len(got)!=2||got[0]!="alpha"||got[1]!="beta"{return errValidation};return nil}
var errValidation=validationError{}
type validationError struct{}
func(validationError)Error()string{return "evidence deduplication failed"}
`},
{ID:"canonical-spec-cache",Category:"spec_cache",Purpose:"Create stable canonical spec fingerprints so repeated builds can reuse verified immutable artifacts.",Source:`package candidate
import("crypto/sha256";"encoding/hex";"encoding/json")
const CandidateID = "canonical-spec-cache"
func Fingerprint(v map[string]string)string{raw,_:=json.Marshal(v);h:=sha256.Sum256(raw);return hex.EncodeToString(h[:])}
func Validate()error{a:=Fingerprint(map[string]string{"b":"2","a":"1"});b:=Fingerprint(map[string]string{"a":"1","b":"2"});if a==""||a!=b{return errValidation};return nil}
type validationError struct{}
func(validationError)Error()string{return "canonical fingerprint unstable"}
var errValidation error=validationError{}
`},
{ID:"repository-path-index",Category:"path_index",Purpose:"Build a read-only path index for faster deterministic evidence lookup.",Source:`package candidate
import "errors"
const CandidateID = "repository-path-index"
func BuildIndex(paths []string)map[string]int{out:=make(map[string]int,len(paths));for i,p:=range paths{if _,ok:=out[p];!ok{out[p]=i}};return out}
func Validate()error{m:=BuildIndex([]string{"a","b","a"});if len(m)!=2||m["a"]!=0||m["b"]!=1{return errors.New("path index mismatch")};return nil}
`},
{ID:"tamper-evident-audit-chain",Category:"audit_integrity",Purpose:"Link audit-event hashes so modifications are detectable; this does not prevent all deletion or compromise.",Source:`package candidate
import("crypto/sha256";"encoding/hex";"errors")
const CandidateID = "tamper-evident-audit-chain"
func Chain(events []string)[]string{out:=make([]string,0,len(events));prev:="";for _,e:=range events{h:=sha256.Sum256([]byte(prev+"\n"+e));prev=hex.EncodeToString(h[:]);out=append(out,prev)};return out}
func Verify(events,hashes []string)bool{if len(events)!=len(hashes){return false};want:=Chain(events);for i:=range want{if want[i]!=hashes[i]{return false}};return true}
func Validate()error{events:=[]string{"created","checked"};if !Verify(events,Chain(events)){return errors.New("valid audit chain rejected")};events[0]="altered";if Verify(events,Chain([]string{"created","checked"})){return errors.New("tamper not detected")};return nil}
`},
{ID:"bounded-input-guard",Category:"input_safety",Purpose:"Reject oversized or path-traversal inputs before proposal generation.",Source:`package candidate
import "errors"
const CandidateID = "bounded-input-guard"
func ValidInput(s string)bool{if len(s)>4096||s==""{return false};for i:=0;i+2<len(s);i++{if s[i:i+3]=="../"{return false}};for _,r:=range s{if r==0{return false}};return true}
func Validate()error{if !ValidInput("safe input")||ValidInput("../outside")||ValidInput(string(make([]byte,4097))){return errors.New("input guard failed")};return nil}
`},
}
func sourceFor(id string)(candidateSpec,bool){for _,s:=range candidateCatalog{if s.ID==id{return s,true}};return candidateSpec{},false}
func validateCandidateSource(s candidateSpec)error{if s.ID==""||s.Category==""||!strings.Contains(s.Source,"func Validate() error") && !strings.Contains(s.Source,"func Validate()error")||!strings.Contains(s.Source,"const CandidateID"){return errors.New("candidate template is incomplete")};fset:=token.NewFileSet();file,err:=parser.ParseFile(fset,s.ID+".go",s.Source,parser.AllErrors);if err!=nil{return fmt.Errorf("candidate %s does not parse: %w",s.ID,err)};allowedImports:=map[string]bool{"errors":true,"fmt":true,"io":true,"strings":true,"strconv":true,"sort":true};for _,item:=range file.Imports{path,err:=strconv.Unquote(item.Path.Value);if err!=nil{return fmt.Errorf("candidate %s has malformed import",s.ID)};allowed:=allowedImports[path]||strings.HasPrefix(path,"crypto/")||strings.HasPrefix(path,"encoding/");if !allowed{return fmt.Errorf("candidate %s imports disallowed package %q",s.ID,path)}};for _,decl:=range file.Decls{if fn,ok:=decl.(*ast.FuncDecl);ok&&fn.Recv==nil&&fn.Name.Name=="init"{return fmt.Errorf("candidate %s defines an init function",s.ID)}};config:=types.Config{Importer:importer.Default()};if _,err:=config.Check("revela-mind.local/core-two/mutations/"+s.ID,fset,[]*ast.File{file},nil);err!=nil{return fmt.Errorf("candidate %s failed static type-check: %w",s.ID,err)};return nil}
