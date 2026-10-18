// Package assemble creates reviewable, offline artifacts from curated fixture data.
package assemble

import (
	"errors"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strings"
)

type Part struct {
	Name string `json:"name"`
	Quantity int `json:"quantity"`
	Notes string `json:"notes"`
}
type Result struct {
	Target string `json:"target"`
	Status string `json:"status"`
	Artifacts []string `json:"artifacts"`
	Parts []Part `json:"parts"`
	Cost string `json:"cost"`
	HumanReviewRequired bool `json:"human_review_required"`
	SafetyNotes []string `json:"safety_notes"`
}

func Generate(target, outDir string) (Result, error) {
	name := strings.ToLower(strings.TrimSpace(target))
	if name != "esp32-sensor" { return Result{Target:name, Status:"needs_curated_template", HumanReviewRequired:true}, errors.New("unknown target; only the curated esp32-sensor fixture is registered; no arbitrary hardware design was fabricated") }
	parts := []Part{{"ESP32-S3 development board",1,"Confirm exact board, USB connector, regulator and selected pin map."},{"BME280 I2C sensor breakout",1,"Confirm voltage compatibility and breakout-board pin labels."},{"3.3V-compatible jumper wires",4,"Use only the correct wire count and insulation for the selected board."},{"Breadboard or suitable prototyping board",1,"Check mechanical and electrical suitability."},{"USB data cable for selected board",1,"Cable and connector vary by board revision."}}
	if err := os.MkdirAll(outDir,0700); err != nil { return Result{},err }
	bom := "USECT-ZERO example BOM\nTarget: esp32-sensor\nPricing: UNVERIFIED — obtain local supplier quotations before purchase.\n\n"
	for _, p := range parts { bom += fmt.Sprintf("- %dx %s — %s\n",p.Quantity,p.Name,p.Notes) }
	wiring := `<svg xmlns="http://www.w3.org/2000/svg" width="900" height="420" viewBox="0 0 900 420"><rect width="900" height="420" fill="#ffffff"/><text x="24" y="38" font-family="sans-serif" font-size="24" font-weight="bold">ESP32-S3 + BME280 I2C — REVIEW DRAFT</text><rect x="50" y="90" width="310" height="245" rx="12" fill="#e8f5e9" stroke="#287d4b" stroke-width="2"/><text x="205" y="125" text-anchor="middle" font-family="sans-serif" font-size="20">ESP32-S3 board</text><text x="85" y="174" font-family="monospace" font-size="17">3V3</text><text x="85" y="218" font-family="monospace" font-size="17">GND</text><text x="85" y="262" font-family="monospace" font-size="17">GPIO 8 (example SDA)</text><text x="85" y="306" font-family="monospace" font-size="17">GPIO 9 (example SCL)</text><rect x="560" y="140" width="270" height="170" rx="12" fill="#e3f2fd" stroke="#1565c0" stroke-width="2"/><text x="695" y="178" text-anchor="middle" font-family="sans-serif" font-size="20">BME280 breakout</text><text x="590" y="220" font-family="monospace" font-size="17">VIN / 3V3</text><text x="590" y="250" font-family="monospace" font-size="17">GND</text><text x="590" y="280" font-family="monospace" font-size="17">SDA / SDI</text><text x="590" y="303" font-family="monospace" font-size="17">SCL / SCK</text><path d="M330 166 L520 216 L560 216" stroke="#e53935" stroke-width="3" fill="none"/><path d="M330 210 L495 246 L560 246" stroke="#424242" stroke-width="3" fill="none"/><path d="M330 254 L470 276 L560 276" stroke="#1565c0" stroke-width="3" fill="none"/><path d="M330 298 L440 296 L530 296 L560 296" stroke="#2e7d32" stroke-width="3" fill="none"/><text x="24" y="385" font-family="sans-serif" font-size="15" fill="#8a1c1c">DRAFT ONLY: GPIO pin assignments vary by board. Verify voltage, pin labels, pull-ups and datasheets before wiring.</text></svg>`
	stl := boxSTL(60,40,3)
	flash := `#!/bin/sh
set -eu
cat <<'NOTE'
USECT-ZERO flash stub — NOT AN EXECUTOR
1. Confirm exact ESP32-S3 board and USB/serial port.
2. Review the source, wiring, voltage levels and vendor instructions.
3. Select and verify a tested firmware image and matching board profile.
4. Only then run your approved local flashing tool manually.
This file intentionally does not call a flashing command.
NOTE
`
	readme := "# esp32-sensor artifact bundle\n\nStatus: review draft, not validated hardware instructions.\nGenerated offline from a curated fixture.\n\n- bom.txt: generic parts list, not priced.\n- wiring.svg: illustrative connection overview; pin mapping must be verified.\n- mount_plate.stl: simple solid 60 x 40 x 3 mm plate without holes; validate clearances and printability.\n- flash.sh: explanatory stub; it does not flash hardware.\n\nNo hardware was connected, no firmware was executed and no component price is asserted.\n"
	files := map[string]string{"bom.txt":bom,"wiring.svg":wiring,"mount_plate.stl":stl,"flash.sh":flash,"README.md":readme}
	names := make([]string,0,len(files))
	for n,c := range files { if err := os.WriteFile(filepath.Join(outDir,n),[]byte(c),0600); err != nil { return Result{},err }; names = append(names,filepath.ToSlash(filepath.Join(outDir,n))) }
	return Result{Target:name,Status:"artifacts_generated_pending_review",Artifacts:names,Parts:parts,Cost:"unverified; local supplier quote required",HumanReviewRequired:true,SafetyNotes:[]string{"No physical operation was performed.","Verify every pin and voltage against the exact board and breakout datasheets.","STL is a flat solid without mounting holes and is not a finished enclosure.","The flash script is a non-executing instruction stub."}},nil
}
func boxSTL(x,y,z int) string {
	v := [8][3]int{{0,0,0},{x,0,0},{x,y,0},{0,y,0},{0,0,z},{x,0,z},{x,y,z},{0,y,z}}
	tris := [][3]int{{0,2,1},{0,3,2},{4,5,6},{4,6,7},{0,1,5},{0,5,4},{1,2,6},{1,6,5},{2,3,7},{2,7,6},{3,0,4},{3,4,7}}
	s := "solid usect_zero_mount_plate_mm\n"
	for _,t := range tris {
		a,b,c := v[t[0]],v[t[1]],v[t[2]]
		u := [3]float64{float64(b[0]-a[0]),float64(b[1]-a[1]),float64(b[2]-a[2])}
		w := [3]float64{float64(c[0]-a[0]),float64(c[1]-a[1]),float64(c[2]-a[2])}
		n := [3]float64{u[1]*w[2]-u[2]*w[1],u[2]*w[0]-u[0]*w[2],u[0]*w[1]-u[1]*w[0]}
		length := math.Sqrt(n[0]*n[0]+n[1]*n[1]+n[2]*n[2]); if length>0 { n[0],n[1],n[2]=n[0]/length,n[1]/length,n[2]/length }
		s += fmt.Sprintf(" facet normal %.1f %.1f %.1f\n  outer loop\n",n[0],n[1],n[2])
		for _,idx := range t { p:=v[idx]; s += fmt.Sprintf("   vertex %d %d %d\n",p[0],p[1],p[2]) }
		s += "  endloop\n endfacet\n"
	}
	return s+"endsolid usect_zero_mount_plate_mm\n"
}
