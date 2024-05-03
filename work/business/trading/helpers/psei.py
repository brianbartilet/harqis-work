from work.business.trading.models.psei import *

ROUND_PRICE = 4


def get_units_available_from_price(price: float, amount_risk: float):
    lots = 0
    for lot_sizing in PSEILots.keys():
        if PSEILots[lot_sizing][0][0] <= price <= PSEILots[lot_sizing][0][1]:
            factor_integer = amount_risk // price
            remainder = (amount_risk // price) % PSEILots[lot_sizing][2]
            lots = factor_integer - remainder
            if lots == 0:
                lots = lot_sizing

            price_ = price - (price % PSEILots[lot_sizing][1])

            #  return lots and actual price
            return int(lots), round(price_, ROUND_PRICE)
        else:
            continue
    return lots, 0


def get_ceiling_price(price: float):
    price_ = price + (0.5 * price)
    return round(price_, ROUND_PRICE)


def normaliz_price(price: float):
    for lot_sizing in PSEILots.keys():
        if PSEILots[lot_sizing][0][0] <= price <= PSEILots[lot_sizing][0][1]:
            remainder = price % PSEILots[lot_sizing][1]
            normalized = price - remainder
            return normalized








