package bom

import (
	"revela-worldwide.local/libs/country"
)

type BOMAdapter struct {
	Country string `json:"country"`
	Currency string `json:"currency"`
	Suppliers []string `json:"suppliers"`
	PriceStatus string `json:"price_status"`
	Note string `json:"note"`
}

func ForCountry(p country.Profile) BOMAdapter {
	return BOMAdapter{
		Country:p.Code, Currency:p.Currency, Suppliers:append([]string(nil),p.Suppliers...),
		PriceStatus:"quote_required",
		Note:"Supplier names are discovery leads only. No live stock, verified part number, shipping, tax, FX rate or price was retrieved.",
	}
}
