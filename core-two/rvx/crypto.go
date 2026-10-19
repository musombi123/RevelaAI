// Package rvx stages optional artifact encryption for future human-reviewed RVX integration.
// It does not change or replace Core-One's current RVX compiler.
package rvx

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"io"
)

const EnvelopeVersion = "rvx-aead-v1"

type Envelope struct { Version string `json:"version"`; Nonce string `json:"nonce"`; Ciphertext string `json:"ciphertext"` }

func Seal(masterKey string,plaintext []byte)(Envelope,error){key,err:=deriveKey(masterKey);if err!=nil{return Envelope{},err};block,err:=aes.NewCipher(key[:]);if err!=nil{return Envelope{},err};gcm,err:=cipher.NewGCM(block);if err!=nil{return Envelope{},err};nonce:=make([]byte,gcm.NonceSize());if _,err:=io.ReadFull(rand.Reader,nonce);err!=nil{return Envelope{},err};ciphertext:=gcm.Seal(nil,nonce,plaintext,[]byte(EnvelopeVersion));return Envelope{Version:EnvelopeVersion,Nonce:base64.RawStdEncoding.EncodeToString(nonce),Ciphertext:base64.RawStdEncoding.EncodeToString(ciphertext)},nil}
func Open(masterKey string,envelope Envelope)([]byte,error){if envelope.Version!=EnvelopeVersion{return nil,errors.New("unsupported RVX envelope version")};key,err:=deriveKey(masterKey);if err!=nil{return nil,err};block,err:=aes.NewCipher(key[:]);if err!=nil{return nil,err};gcm,err:=cipher.NewGCM(block);if err!=nil{return nil,err};nonce,err:=base64.RawStdEncoding.DecodeString(envelope.Nonce);if err!=nil||len(nonce)!=gcm.NonceSize(){return nil,errors.New("invalid RVX envelope nonce")};ciphertext,err:=base64.RawStdEncoding.DecodeString(envelope.Ciphertext);if err!=nil{return nil,errors.New("invalid RVX envelope ciphertext")};plain,err:=gcm.Open(nil,nonce,ciphertext,[]byte(EnvelopeVersion));if err!=nil{return nil,errors.New("RVX envelope authentication failed")};return plain,nil}
func deriveKey(masterKey string)([32]byte,error){if len(masterKey)<32{return [32]byte{},errors.New("RVX master key must contain at least 32 bytes")};return sha256.Sum256([]byte(masterKey)),nil}
func Probe()(bool,string){const key="fixture-only-key-not-a-production-secret-0123456789";plain:=[]byte("rvx proposal fixture");envelope,err:=Seal(key,plain);if err!=nil{return false,"encryption_failed"};opened,err:=Open(key,envelope);if err!=nil||string(opened)!=string(plain){return false,"round_trip_failed"};if len(envelope.Ciphertext)==0{return false,"empty_ciphertext"};bad:=envelope;if bad.Ciphertext[0]=='A'{bad.Ciphertext="B"+bad.Ciphertext[1:]}else{bad.Ciphertext="A"+bad.Ciphertext[1:]};if _,err:=Open(key,bad);err==nil{return false,"tamper_not_detected"};return true,"AES-GCM round-trip and tamper-detection probe passed; this is artifact protection, not an uncopyability guarantee"}
