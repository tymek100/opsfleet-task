"""A tool is a validated input schema plus an async Python function."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from google.genai import types
from pydantic import BaseModel, ConfigDict, ValidationError


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[ToolArgs]
    handler: Callable[..., Awaitable[dict]]

    def declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters_json_schema=self.args.model_json_schema(),
        )

    async def invoke(self, arguments: dict) -> dict:
        try:
            validated = self.args.model_validate(arguments)
        except ValidationError:
            return {"error": "Invalid arguments. Follow this tool's JSON schema."}
        return await self.handler(**validated.model_dump())
