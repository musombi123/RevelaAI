module revela-genesis.local/core-one

go 1.23

require (
	revela-worldwide.local/libs v0.0.0
)

// Use the local worldwide library so development and testing use the
// checked-out source instead of a remotely downloaded module version.
replace revela-worldwide.local/libs => ../lib/worldwide
