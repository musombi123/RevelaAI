package candidate
import("crypto/aes";"crypto/cipher";"crypto/rand";"crypto/sha256";"errors";"io")
const CandidateID="rvx-aead-envelope"
func Seal(key string,p []byte)([]byte,error){if len(key)<32{return nil,errors.New("key too short")};k:=sha256.Sum256([]byte(key));b,e:=aes.NewCipher(k[:]);if e!=nil{return nil,e};g,e:=cipher.NewGCM(b);if e!=nil{return nil,e};n:=make([]byte,g.NonceSize());if _,e=io.ReadFull(rand.Reader,n);e!=nil{return nil,e};return append(n,g.Seal(nil,n,p,[]byte("rvx-aead-v1"))...),nil}
func Open(key string,v []byte)([]byte,error){if len(key)<32{return nil,errors.New("key too short")};k:=sha256.Sum256([]byte(key));b,e:=aes.NewCipher(k[:]);if e!=nil{return nil,e};g,e:=cipher.NewGCM(b);if e!=nil{return nil,e};if len(v)<g.NonceSize(){return nil,errors.New("box too small")};return g.Open(nil,v[:g.NonceSize()],v[g.NonceSize():],[]byte("rvx-aead-v1"))}
func Validate()error{k:="fixture-only-external-key-with-32-bytes-or-more";v,e:=Seal(k,[]byte("x"));if e!=nil{return e};p,e:=Open(k,v);if e!=nil||string(p)!="x"{return errors.New("round trip failed")};v[len(v)-1]^=1;if _,e=Open(k,v);e==nil{return errors.New("tampering missed")};return nil}
