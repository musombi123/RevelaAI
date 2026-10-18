package genesis

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

func (e *Engine) Enqueue(demand, source string) (Demand, error) {
	demand = strings.TrimSpace(demand)
	if demand == "" || len(demand) > 3999 { return Demand{}, errors.New("demand must contain 1 to 3999 characters") }
	decision := e.Guardian.Check(demand)
	if !decision.Allowed {
		if err := e.Guardian.LogBlocked("queued_demand", demand, decision.Reason); err != nil { return Demand{}, fmt.Errorf("guardian blocked demand and audit logging failed: %w", err) }
		e.publish(Event{Type:"blocked",At:time.Now().UTC(),Message:"Guardian blocked a queued demand before it entered the queue.",Status:decision.Code})
		return Demand{}, ErrBlocked
	}
	item := Demand{ID:newID("demand"),Demand:demand,Source:limitText(source,100),CreatedAt:time.Now().UTC(),Status:"queued"}
	if err:=writeJSON(filepath.Join(e.CoreRoot,"state","queue","pending",item.ID+".json"),item);err!=nil{return Demand{},fmt.Errorf("persist queued demand: %w",err)}
	e.publish(Event{Type:"demand_queued",At:time.Now().UTC(),Message:"A validated demand was durably queued for daemon processing.",Status:"queued"})
	return item,nil
}

// RunDaemon scans on startup, then at the configured interval. Every cycle emits an event
// when a subsystem fails, instead of silently discarding errors.
func (e *Engine) RunDaemon(ctx context.Context, interval time.Duration) {
	if interval<=0 { interval=60*time.Second }
	e.runCycle(ctx)
	ticker:=time.NewTicker(interval);defer ticker.Stop()
	for { select { case <-ctx.Done():return; case <-ticker.C:e.runCycle(ctx) } }
}
func (e *Engine) runCycle(ctx context.Context) {
	if err:=e.EyeScan(ctx);err!=nil&&!errors.Is(err,ErrBlocked){e.publish(Event{Type:"eye_scan_error",At:time.Now().UTC(),Message:limitText(err.Error(),240),Status:"retry_next_cycle"})}
	if err:=e.ProcessQueue(ctx);err!=nil&&!errors.Is(err,context.Canceled)&&!errors.Is(err,context.DeadlineExceeded){e.publish(Event{Type:"queue_error",At:time.Now().UTC(),Message:limitText(err.Error(),240),Status:"retry_next_cycle"})}
}

// ProcessQueue claims each item with an atomic rename into processing/. A crash leaves the
// claim recoverable; a queue file is removed only after its final status is durably written.
func (e *Engine) ProcessQueue(ctx context.Context) error {
	e.queueMu.Lock();defer e.queueMu.Unlock()
	root:=filepath.Join(e.CoreRoot,"state","queue");pending:=filepath.Join(root,"pending");processing:=filepath.Join(root,"processing")
	if err:=os.MkdirAll(pending,0700);err!=nil{return err};if err:=os.MkdirAll(processing,0700);err!=nil{return err}
	firstErr:=e.recoverProcessing(root,pending,processing)
	entries,err:=os.ReadDir(pending);if err!=nil{return err}
	sort.Slice(entries,func(i,j int)bool{return entries[i].Name()<entries[j].Name()})
	for _,entry:=range entries {
		if entry.IsDir()||!strings.HasSuffix(entry.Name(),".json"){continue}
		select{case <-ctx.Done():return ctx.Err();default:}
		src:=filepath.Join(pending,entry.Name());info,err:=os.Lstat(src)
		if err!=nil{if firstErr==nil&&!os.IsNotExist(err){firstErr=err};continue}
		if !info.Mode().IsRegular(){
			if err:=os.Rename(src,filepath.Join(root,"failed",entry.Name()+".unsafe-entry"));err!=nil&&firstErr==nil{firstErr=fmt.Errorf("quarantine non-regular queue entry: %w",err)}
			continue
		}
		claim:=filepath.Join(processing,entry.Name())
		if err:=os.Rename(src,claim);err!=nil{if !os.IsNotExist(err)&&firstErr==nil{firstErr=err};continue}
		raw,err:=os.ReadFile(claim);if err!=nil{if firstErr==nil{firstErr=err};continue}
		var item Demand
		if err:=json.Unmarshal(raw,&item);err!=nil||item.ID==""||strings.TrimSpace(item.Demand)==""{
			if err==nil{err=errors.New("queue record is missing id or demand")}
			if moveErr:=moveQueueFile(claim,filepath.Join(root,"failed",entry.Name()));moveErr!=nil&&firstErr==nil{firstErr=fmt.Errorf("quarantine invalid queue record (%v): %w",err,moveErr)} else if firstErr==nil{firstErr=fmt.Errorf("invalid queue record %s: %w",entry.Name(),err)}
			continue
		}
		item.Status="processing";item.Error=""
		if err:=writeJSON(claim,item);err!=nil{if firstErr==nil{firstErr=fmt.Errorf("persist processing state: %w",err)};_ = os.Rename(claim,src);continue}
		inv,inventErr:=e.Invent(ctx,item.Demand)
		if inventErr!=nil&&errors.Is(inventErr,ErrAlreadyExists){
			if existingName,sameDemand:=e.findExistingInvention(item.Demand);sameDemand{item.Status="await_merge";item.Source=existingName}else{item.Status="failed";item.Error="an invention with the derived name already exists for a different demand; inspect it manually"}
		}else if inventErr!=nil{
			if errors.Is(inventErr,ErrBlocked){item.Status="blocked";item.Error="Guardian blocked the demand; no new invention was generated."}else{item.Status="failed";item.Error=limitText(inventErr.Error(),500);if firstErr==nil{firstErr=fmt.Errorf("process queued demand %s: %w",item.ID,inventErr)}}
		}else{item.Status="await_merge";item.Source=inv.Name}
		dest:=filepath.Join(root,item.Status,entry.Name())
		if err:=writeJSON(dest,item);err!=nil{if firstErr==nil{firstErr=fmt.Errorf("persist final queue status %q: %w",item.Status,err)};continue}
		if err:=os.Remove(claim);err!=nil{if firstErr==nil{firstErr=fmt.Errorf("remove completed queue claim: %w",err)};continue}
		e.publish(Event{Type:"queue_processed",At:time.Now().UTC(),Message:"Daemon processed a queued demand; any generated invention remains awaiting owner merge.",Invention:item.Source,Status:item.Status})
	}
	return firstErr
}

func (e *Engine) recoverProcessing(root,pending,processing string) error {
	entries,err:=os.ReadDir(processing);if err!=nil{return err};var firstErr error
	for _,entry:=range entries {
		if entry.IsDir()||!strings.HasSuffix(entry.Name(),".json"){continue}
		src:=filepath.Join(processing,entry.Name());dest:=filepath.Join(pending,entry.Name())
		_,statErr:=os.Lstat(dest)
		if statErr==nil { if firstErr==nil{firstErr=fmt.Errorf("duplicate pending/processing queue record %s",entry.Name())};continue }
		if !os.IsNotExist(statErr){if firstErr==nil{firstErr=statErr};continue}
		raw,err:=os.ReadFile(src);if err!=nil{if firstErr==nil{firstErr=err};continue}
		var item Demand
		if err:=json.Unmarshal(raw,&item);err!=nil||item.ID==""||strings.TrimSpace(item.Demand)==""{
			if err==nil{err=errors.New("queue record is missing id or demand")}
			if moveErr:=moveQueueFile(src,filepath.Join(root,"failed",entry.Name()));moveErr!=nil&&firstErr==nil{firstErr=fmt.Errorf("quarantine interrupted invalid queue record (%v): %w",err,moveErr)}
			continue
		}
		item.Status="queued";item.Error="recovered after an interrupted processing attempt"
		if err:=writeJSON(dest,item);err!=nil{if firstErr==nil{firstErr=fmt.Errorf("recover queue record: %w",err)};continue}
		if err:=os.Remove(src);err!=nil&&firstErr==nil{firstErr=err}
	}
	return firstErr
}

func (e *Engine) findExistingInvention(demand string)(string,bool){
	name:=deriveSpec(demand).Name;raw,err:=os.ReadFile(filepath.Join(e.CoreRoot,"inventions",name,"evidence.json"));if err!=nil{return "",false}
	var envelope struct{Specification ToolSpec}
	if json.Unmarshal(raw,&envelope)!=nil||strings.TrimSpace(envelope.Specification.Demand)!=strings.TrimSpace(demand){return "",false}
	return name,true
}
func moveQueueFile(src,dest string)error{
	raw,err:=os.ReadFile(src);if err!=nil{return err};if err:=atomicWrite(dest,raw,0600);err!=nil{return err};return os.Remove(src)
}
