from pydantic import BaseModel


class MeResponse(BaseModel):
    sub: str
    username: str
    roles: list[str]
    groups: list[str]
