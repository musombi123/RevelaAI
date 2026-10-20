// Command revela builds and composes the three existing cores without editing their source.
package main
import("context";"crypto/sha256";"errors";"flag";"fmt";"log";"net/http";"os";"os/exec";"os/signal";"path/filepath";"runtime";"strings";"sync";"syscall";"time")
type serviceSpec struct{name,moduleDir,packagePath,binaryName,listen,health string;args []string}
func main(){
 if err:=verifyOwnerRecipe();err!=nil{log.Fatal(err)}
 rootFlag:=flag.String("repo-root",".","repository root");zero:=flag.String("zero-listen","127.0.0.1:8780","ZERO listener");one:=flag.String("genesis-listen","127.0.0.1:8781","ONE listener");two:=flag.String("mind-listen","127.0.0.1:8782","TWO listener");interval:=flag.Duration("mind-interval",24*time.Hour,"Mind improvement cycle interval");daemon:=flag.Bool("daemon",false,"start ZERO + ONE + TWO together");flag.Parse();if !*daemon{fmt.Fprintln(os.Stderr,"Use --daemon to start ZERO + ONE + TWO together.");os.Exit(2)}
 root,err:=filepath.Abs(*rootFlag);if err!=nil{log.Fatal(err)};for _,p:=range []string{"core-zero/go.mod","core-one/go.mod","core-two/go.mod"}{if info,e:=os.Stat(filepath.Join(root,p));e!=nil||info.IsDir(){log.Fatalf("required module missing: %s",p)}}
 tmp,err:=os.MkdirTemp("","revela-core-stack-");if err!=nil{log.Fatal(err)};defer os.RemoveAll(tmp);suffix:="";if runtime.GOOS=="windows"{suffix=".exe"}
 specs:=[]serviceSpec{{name:"ZERO",moduleDir:filepath.Join(root,"core-zero"),packagePath:"./cmd/usect-zero",binaryName:"usect-zero"+suffix,listen:*zero,health:"/v1/health",args:[]string{"-mode","serve","-root",root,"-listen",*zero}},{name:"ONE",moduleDir:filepath.Join(root,"core-one"),packagePath:"./cmd/genesis",binaryName:"revela-genesis"+suffix,listen:*one,health:"/v1/genesis/health",args:[]string{"-mode","serve","-repo-root",root,"-listen",*one}},{name:"TWO",moduleDir:filepath.Join(root,"core-two"),packagePath:"./cmd/revela-mind",binaryName:"revela-mind"+suffix,listen:*two,health:"/v1/mind/health",args:[]string{"-daemon","-repo-root",root,"-listen",*two,"-interval",interval.String()}}}
 for _,s:=range specs{cmd:=exec.Command("go","build","-o",filepath.Join(tmp,s.binaryName),s.packagePath);cmd.Dir=s.moduleDir;cmd.Stdout=os.Stdout;cmd.Stderr=os.Stderr;if err:=cmd.Run();err!=nil{log.Fatalf("build %s failed: %v",s.name,err)}}
 ctx,stop:=signal.NotifyContext(context.Background(),os.Interrupt,syscall.SIGTERM);defer stop();var wg sync.WaitGroup;exits:=make(chan error,len(specs))
 for _,s:=range specs{spec:=s;cmd:=exec.CommandContext(ctx,filepath.Join(tmp,spec.binaryName),spec.args...);cmd.Dir=spec.moduleDir;cmd.Stdout=os.Stdout;cmd.Stderr=os.Stderr;cmd.Env=os.Environ();if err:=cmd.Start();err!=nil{stop();log.Fatalf("start %s failed: %v",spec.name,err)};wg.Add(1);go func(name string,c *exec.Cmd){defer wg.Done();err:=c.Wait();if err!=nil&&!errors.Is(err,context.Canceled){exits<-fmt.Errorf("%s exited: %w",name,err)}else{exits<-fmt.Errorf("%s stopped",name)};stop()}(spec.name,cmd)}
 for _,s:=range specs{if err:=waitHealthy(ctx,s.listen,s.health,35*time.Second);err!=nil{stop();log.Fatalf("%s health check failed: %v",s.name,err)};fmt.Fprintf(os.Stderr,"%s healthy at http://%s%s\n",s.name,s.listen,s.health)}
 fmt.Fprintln(os.Stderr,"Revela stack running: ZERO (Body) ↔ ONE (Womb) ↔ TWO (Mind). Human review remains required.")
 select{case<-ctx.Done():case err:=<-exits:log.Print(err)};stop();wg.Wait()
}
func waitHealthy(ctx context.Context,address,path string,timeout time.Duration)error{deadline:=time.NewTimer(timeout);defer deadline.Stop();ticker:=time.NewTicker(250*time.Millisecond);defer ticker.Stop();client:=&http.Client{Timeout:800*time.Millisecond};for{req,_:=http.NewRequestWithContext(ctx,http.MethodGet,"http://"+strings.TrimSpace(address)+path,nil);if req!=nil{resp,err:=client.Do(req);if err==nil{_ = resp.Body.Close();if resp.StatusCode>=200&&resp.StatusCode<300{return nil}}};select{case<-ctx.Done():return ctx.Err();case<-deadline.C:return fmt.Errorf("health deadline exceeded for http://%s%s",address,path);case<-ticker.C:}}}


func verifyOwnerRecipe() error {
    mode := strings.ToLower(strings.TrimSpace(os.Getenv("REVELA_UNCOPYABLE_ENFORCE")))
    if mode != "1" && mode != "true" && mode != "yes" && mode != "on" {
        return nil
    }
    path := strings.TrimSpace(os.Getenv("REVELA_MASTER_KEY_PATH"))
    if path == "" {
        home, err := os.UserHomeDir()
        if err != nil {
            return fmt.Errorf("Need RevelaCode Brain - Contact founder: owner home is unavailable")
        }
        path = filepath.Join(home, ".revela_recipe", "master.key")
    }
    key, err := os.ReadFile(path)
    if err != nil {
        return fmt.Errorf("Need RevelaCode Brain - Contact founder: owner recipe is unavailable")
    }
    if len(key) != 512 {
        return fmt.Errorf("Need RevelaCode Brain - Contact founder: owner recipe length is invalid")
    }
    expected := strings.TrimSpace(os.Getenv("REVELA_RECIPE_EXPECTED_SHA256"))
    if expected != "" {
        digest := sha256.Sum256(key)
        if !strings.EqualFold(fmt.Sprintf("%x", digest), expected) {
            return fmt.Errorf("Need RevelaCode Brain - Contact founder: owner recipe fingerprint mismatch")
        }
    }
    return nil
}
