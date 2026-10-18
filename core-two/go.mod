module revela-mind.local/core-two

go 1.23

require (
	revela-genesis.local/core-one v0.0.0
	usect-zero.local/core-zero v0.0.0
)

replace revela-genesis.local/core-one => ../core-one
replace usect-zero.local/core-zero => ../core-zero
