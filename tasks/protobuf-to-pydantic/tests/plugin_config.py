"""Configuration module loaded by the protobuf-to-pydantic protoc plugin during the plugin-flow tests.

The plugin reads this file via ``--protobuf-to-pydantic_out=config_path=<this file>:<out>``. It supplies the
``local`` template variables referenced by the demo protos (``p2p@local|CustomerField`` etc.), a custom
``Template`` implementing the ``p2p@timestamp|...`` template hook, and the list of rule packages to ignore.
"""
from typing import List, Type

from google.protobuf.any_pb2 import Any  # type: ignore
from pydantic import confloat, conint
from pydantic.fields import FieldInfo

from protobuf_to_pydantic.template import Template


class CustomerField(FieldInfo):
    pass


def customer_any() -> Any:
    return Any()


class CustomCommentTemplate(Template):
    def template_timestamp(self, length_str: str) -> int:
        timestamp: float = 1600000000
        if length_str == "10":
            return int(timestamp)
        elif length_str == "13":
            return int(timestamp * 100)
        raise KeyError(f"timestamp template not support value:{length_str}")


local_dict = {
    "CustomerField": CustomerField,
    "confloat": confloat,
    "conint": conint,
    "customer_any": customer_any,
}
comment_prefix = "p2p"
template: Type[Template] = CustomCommentTemplate
ignore_pkg_list: List[str] = ["validate", "p2p_validate"]
file_name_suffix = "_p2p"
