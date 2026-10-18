// Package provider connects Mind to the same RevelaCode provider credential pair as Core-One.
package provider

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

type Mesh struct { BaseURL string; Key string; Client *http.Client }
func FromEnvironment() Mesh { return Mesh{BaseURL:strings.TrimRight(strings.TrimSpace(os.Getenv("REVELACODE_PROVIDER_URL")),"/"),Key:strings.TrimSpace(os.Getenv("REVELACODE_PROVIDER_KEY")),Client:&http.Client{Timeout:8*time.Second}} }
func(m Mesh)Configured()bool{return m.BaseURL!=""&&m.Key!=""}
// NotifyEvolution publishes proposal metadata only; source files, secrets and prompts are excluded.
func(m Mesh)NotifyEvolution(ctx context.Context,metadata map[string]any)error{
 if !m.Configured(){return errors.New("RevelaCode provider URL/key are not configured")};endpoint,err:=url.Parse(m.BaseURL);if err!=nil||endpoint.Host==""||endpoint.User!=nil||endpoint.RawQuery!=""||endpoint.Fragment!=""{return errors.New("RevelaCode provider URL is invalid")}
 local:=strings.EqualFold(endpoint.Hostname(),"localhost");if ip:=net.ParseIP(endpoint.Hostname());ip!=nil&&ip.IsLoopback(){local=true};if endpoint.Scheme!="https"&&!(endpoint.Scheme=="http"&&local){return errors.New("RevelaCode provider must use HTTPS unless it is a loopback test endpoint")}
 body,err:=json.Marshal(map[string]any{"core":"USECT-TWO","event":"evolution_proposed","metadata":metadata,"at":time.Now().UTC()});if err!=nil{return err};request,err:=http.NewRequestWithContext(ctx,http.MethodPost,m.BaseURL+"/v1/mind/provider/heartbeat",bytes.NewReader(body));if err!=nil{return err};request.Header.Set("Content-Type","application/json");request.Header.Set("User-Agent","RevelaMind/0.1.0");request.Header.Set("Authorization","Bearer "+m.Key)
 client:=m.Client;if client==nil{client=&http.Client{Timeout:8*time.Second}};response,err:=client.Do(request);if err!=nil{return err};defer response.Body.Close();if response.StatusCode<200||response.StatusCode>=300{return errors.New("RevelaCode provider rejected Mind metadata")};return nil
}
