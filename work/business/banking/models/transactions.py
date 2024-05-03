from core.web.services.core.json import JsonObject


class DtoStatementTransaction(JsonObject):
    payee: str = None
    memo: str = None
    amount: str = None
    date: str = None

