"""Process configuration models.

职责：
1. 保存工艺配置中心的基础库、节点和路线数据。
2. 为后续财务模型配置、路线编排和导入导出提供持久化结构。
3. 统一使用英文状态值入库，前端负责展示中文文案。
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.models.base import Base, TimestampMixin


class SoftDeleteMixin:
    """软删除字段，沿用现有业务表 is_deleted + deleted_at 写法。"""

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否删除")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="删除时间")


class OperatorMixin:
    """创建人与更新人字段，保持工艺配置主数据的审计来源。"""

    @declared_attr
    def created_by(cls) -> Mapped[int | None]:
        return mapped_column(ForeignKey("users.id"), nullable=True, comment="创建人ID，关联users.id")

    @declared_attr
    def updated_by(cls) -> Mapped[int | None]:
        return mapped_column(ForeignKey("users.id"), nullable=True, comment="更新人ID，关联users.id")


class ProcessMaterial(TimestampMixin, OperatorMixin, SoftDeleteMixin, Base):
    """原料库主表。"""

    __tablename__ = "process_materials"
    __table_args__ = (
        UniqueConstraint("code", name="uk_process_materials_code"),
        Index("idx_process_materials_type", "type"),
        Index("idx_process_materials_status", "status"),
        Index("idx_process_materials_sort_order", "sort_order"),
        Index("idx_process_materials_is_deleted", "is_deleted"),
        Index("idx_process_materials_deleted_at", "deleted_at"),
        {"comment": "工艺配置原料库"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    code: Mapped[str] = mapped_column(String(100), nullable=False, comment="原料编码")
    name: Mapped[str] = mapped_column(String(150), nullable=False, comment="原料名称")
    type: Mapped[str] = mapped_column(String(100), nullable=False, comment="原料类型")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="描述信息")
    unit: Mapped[str] = mapped_column(String(50), nullable=False, comment="单位")
    status: Mapped[str] = mapped_column(String(30), default="enabled", nullable=False, comment="状态：enabled/draft/disabled")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序值")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class ProcessProduct(TimestampMixin, OperatorMixin, SoftDeleteMixin, Base):
    """产品库主表。"""

    __tablename__ = "process_products"
    __table_args__ = (
        UniqueConstraint("code", name="uk_process_products_code"),
        Index("idx_process_products_type", "type"),
        Index("idx_process_products_status", "status"),
        Index("idx_process_products_sort_order", "sort_order"),
        Index("idx_process_products_is_deleted", "is_deleted"),
        Index("idx_process_products_deleted_at", "deleted_at"),
        {"comment": "工艺配置产品库"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    code: Mapped[str] = mapped_column(String(100), nullable=False, comment="产品编码")
    name: Mapped[str] = mapped_column(String(150), nullable=False, comment="产品名称")
    type: Mapped[str] = mapped_column(String(100), nullable=False, comment="产品类型")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="描述信息")
    unit: Mapped[str] = mapped_column(String(50), nullable=False, comment="单位")
    status: Mapped[str] = mapped_column(String(30), default="enabled", nullable=False, comment="状态：enabled/draft/disabled")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序值")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class ProcessConsumable(TimestampMixin, OperatorMixin, SoftDeleteMixin, Base):
    """消耗品库主表。"""

    __tablename__ = "process_consumables"
    __table_args__ = (
        UniqueConstraint("code", name="uk_process_consumables_code"),
        Index("idx_process_consumables_type", "type"),
        Index("idx_process_consumables_status", "status"),
        Index("idx_process_consumables_sort_order", "sort_order"),
        Index("idx_process_consumables_is_deleted", "is_deleted"),
        Index("idx_process_consumables_deleted_at", "deleted_at"),
        {"comment": "工艺配置消耗品库"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    code: Mapped[str] = mapped_column(String(100), nullable=False, comment="消耗品编码")
    name: Mapped[str] = mapped_column(String(150), nullable=False, comment="消耗品名称")
    type: Mapped[str] = mapped_column(String(100), nullable=False, comment="消耗品类型")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="描述信息")
    unit: Mapped[str] = mapped_column(String(50), nullable=False, comment="单位")
    status: Mapped[str] = mapped_column(String(30), default="enabled", nullable=False, comment="状态：enabled/draft/disabled")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序值")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class ProcessPublicService(TimestampMixin, OperatorMixin, SoftDeleteMixin, Base):
    """公共服务库主表。"""

    __tablename__ = "process_public_services"
    __table_args__ = (
        UniqueConstraint("code", name="uk_process_public_services_code"),
        Index("idx_process_public_services_type", "type"),
        Index("idx_process_public_services_status", "status"),
        Index("idx_process_public_services_sort_order", "sort_order"),
        Index("idx_process_public_services_is_deleted", "is_deleted"),
        Index("idx_process_public_services_deleted_at", "deleted_at"),
        {"comment": "工艺配置公共服务库"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    code: Mapped[str] = mapped_column(String(100), nullable=False, comment="公共服务编码")
    name: Mapped[str] = mapped_column(String(150), nullable=False, comment="公共服务名称")
    type: Mapped[str] = mapped_column(String(100), nullable=False, comment="公共服务类型")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="描述信息")
    unit: Mapped[str] = mapped_column(String(50), nullable=False, comment="单位")
    status: Mapped[str] = mapped_column(String(30), default="enabled", nullable=False, comment="状态：enabled/draft/disabled")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序值")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class ProcessRegionPrice(TimestampMixin, OperatorMixin, SoftDeleteMixin, Base):
    """区域单价表，按 owner_type + owner_id 关联四类基础库。"""

    __tablename__ = "process_region_prices"
    __table_args__ = (
        Index("idx_process_region_prices_owner", "owner_type", "owner_id"),
        Index("idx_process_region_prices_region", "region_code"),
        Index("idx_process_region_prices_status", "status"),
        Index("idx_process_region_prices_is_deleted", "is_deleted"),
        Index("idx_process_region_prices_deleted_at", "deleted_at"),
        {"comment": "工艺配置区域单价表"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    owner_type: Mapped[str] = mapped_column(String(30), nullable=False, comment="归属类型：material/product/consumable/public_service")
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="归属基础库ID")
    region_code: Mapped[str] = mapped_column(String(30), nullable=False, comment="区域编码：asia/europe/americas")
    region_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="区域名称")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, comment="币种：CNY/EUR/USD")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0, nullable=False, comment="单位价格")
    unit: Mapped[str] = mapped_column(String(50), nullable=False, comment="计价单位")
    status: Mapped[str] = mapped_column(String(30), default="enabled", nullable=False, comment="状态：enabled/draft/disabled")


class ProcessNode(TimestampMixin, OperatorMixin, SoftDeleteMixin, Base):
    """工艺节点主表。"""

    __tablename__ = "process_nodes"
    __table_args__ = (
        UniqueConstraint("code", name="uk_process_nodes_code"),
        Index("idx_process_nodes_node_type", "node_type"),
        Index("idx_process_nodes_status", "status"),
        Index("idx_process_nodes_sort_order", "sort_order"),
        Index("idx_process_nodes_is_deleted", "is_deleted"),
        Index("idx_process_nodes_deleted_at", "deleted_at"),
        {"comment": "工艺节点库"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    code: Mapped[str] = mapped_column(String(100), nullable=False, comment="节点编码")
    name: Mapped[str] = mapped_column(String(150), nullable=False, comment="节点名称")
    node_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="节点类型：pretreatment/hydrometallurgy/pyrometallurgy/post_treatment",
    )
    staff: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0, nullable=False, comment="人员数量")
    area: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False, comment="占地面积")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="描述信息")
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False, comment="状态：enabled/draft/disabled")
    version: Mapped[str] = mapped_column(String(50), default="1.0", nullable=False, comment="版本号")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序值")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class ProcessNodeMaterialInput(TimestampMixin, SoftDeleteMixin, Base):
    """工艺节点输入原料。"""

    __tablename__ = "process_node_material_inputs"
    __table_args__ = (
        Index("idx_process_node_material_inputs_node_id", "node_id"),
        Index("idx_process_node_material_inputs_material_id", "material_id"),
        Index("idx_process_node_material_inputs_is_deleted", "is_deleted"),
        {"comment": "工艺节点输入原料"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    node_id: Mapped[int] = mapped_column(ForeignKey("process_nodes.id"), nullable=False, comment="工艺节点ID")
    material_id: Mapped[int] = mapped_column(ForeignKey("process_materials.id"), nullable=False, comment="原料ID")
    amount_per_ton: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0, nullable=False, comment="每吨原料投入量")
    unit: Mapped[str] = mapped_column(String(50), nullable=False, comment="单位")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序值")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class ProcessNodeConsumable(TimestampMixin, SoftDeleteMixin, Base):
    """工艺节点消耗品用量。"""

    __tablename__ = "process_node_consumables"
    __table_args__ = (
        Index("idx_process_node_consumables_node_id", "node_id"),
        Index("idx_process_node_consumables_consumable_id", "consumable_id"),
        Index("idx_process_node_consumables_is_deleted", "is_deleted"),
        {"comment": "工艺节点消耗品用量"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    node_id: Mapped[int] = mapped_column(ForeignKey("process_nodes.id"), nullable=False, comment="工艺节点ID")
    consumable_id: Mapped[int] = mapped_column(ForeignKey("process_consumables.id"), nullable=False, comment="消耗品ID")
    amount_per_ton: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0, nullable=False, comment="每吨原料消耗量")
    unit: Mapped[str] = mapped_column(String(50), nullable=False, comment="单位")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序值")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class ProcessNodePublicService(TimestampMixin, SoftDeleteMixin, Base):
    """工艺节点公共服务消耗。"""

    __tablename__ = "process_node_public_services"
    __table_args__ = (
        Index("idx_process_node_public_services_node_id", "node_id"),
        Index("idx_process_node_public_services_service_id", "public_service_id"),
        Index("idx_process_node_public_services_is_deleted", "is_deleted"),
        {"comment": "工艺节点公共服务消耗"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    node_id: Mapped[int] = mapped_column(ForeignKey("process_nodes.id"), nullable=False, comment="工艺节点ID")
    public_service_id: Mapped[int] = mapped_column(ForeignKey("process_public_services.id"), nullable=False, comment="公共服务ID")
    amount_per_ton: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0, nullable=False, comment="每吨原料消耗量")
    unit: Mapped[str] = mapped_column(String(50), nullable=False, comment="单位")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序值")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class ProcessNodeEquipment(TimestampMixin, SoftDeleteMixin, Base):
    """工艺节点设备和投资。"""

    __tablename__ = "process_node_equipment"
    __table_args__ = (
        Index("idx_process_node_equipment_node_id", "node_id"),
        Index("idx_process_node_equipment_is_deleted", "is_deleted"),
        {"comment": "工艺节点设备投资"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    node_id: Mapped[int] = mapped_column(ForeignKey("process_nodes.id"), nullable=False, comment="工艺节点ID")
    equipment_name: Mapped[str] = mapped_column(String(150), nullable=False, comment="设备名称")
    equipment_type: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="设备类型")
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False, comment="设备数量")
    investment_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False, comment="投资金额")
    currency: Mapped[str] = mapped_column(String(10), default="CNY", nullable=False, comment="币种")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序值")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class ProcessNodeOutput(TimestampMixin, SoftDeleteMixin, Base):
    """工艺节点输出产品。"""

    __tablename__ = "process_node_outputs"
    __table_args__ = (
        Index("idx_process_node_outputs_node_id", "node_id"),
        Index("idx_process_node_outputs_product_id", "product_id"),
        Index("idx_process_node_outputs_is_deleted", "is_deleted"),
        {"comment": "工艺节点输出产品"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    node_id: Mapped[int] = mapped_column(ForeignKey("process_nodes.id"), nullable=False, comment="工艺节点ID")
    product_id: Mapped[int] = mapped_column(ForeignKey("process_products.id"), nullable=False, comment="产品ID")
    output_per_ton: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0, nullable=False, comment="每吨原料产出量")
    unit: Mapped[str] = mapped_column(String(50), nullable=False, comment="单位")
    is_main_product: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否主产品")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序值")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class ProcessRoute(TimestampMixin, OperatorMixin, SoftDeleteMixin, Base):
    """工艺路线主表。"""

    __tablename__ = "process_routes"
    __table_args__ = (
        UniqueConstraint("code", name="uk_process_routes_code"),
        Index("idx_process_routes_input_material_id", "input_material_id"),
        Index("idx_process_routes_final_product_id", "final_product_id"),
        Index("idx_process_routes_status", "status"),
        Index("idx_process_routes_sort_order", "sort_order"),
        Index("idx_process_routes_is_deleted", "is_deleted"),
        Index("idx_process_routes_deleted_at", "deleted_at"),
        {"comment": "工艺路线库"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    code: Mapped[str] = mapped_column(String(100), nullable=False, comment="路线编码")
    name: Mapped[str] = mapped_column(String(150), nullable=False, comment="路线名称")
    input_material_id: Mapped[int] = mapped_column(ForeignKey("process_materials.id"), nullable=False, comment="输入原料ID")
    final_product_id: Mapped[int] = mapped_column(ForeignKey("process_products.id"), nullable=False, comment="最终产品ID")
    version: Mapped[str] = mapped_column(String(50), default="1.0", nullable=False, comment="版本号")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="描述信息")
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False, comment="状态：enabled/draft/disabled")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序值")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class ProcessRouteNode(TimestampMixin, SoftDeleteMixin, Base):
    """工艺路线节点链路。"""

    __tablename__ = "process_route_nodes"
    __table_args__ = (
        Index("idx_process_route_nodes_route_id", "route_id"),
        Index("idx_process_route_nodes_node_id", "node_id"),
        Index("idx_process_route_nodes_sort_order", "sort_order"),
        Index("idx_process_route_nodes_is_deleted", "is_deleted"),
        {"comment": "工艺路线节点链路"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    route_id: Mapped[int] = mapped_column(ForeignKey("process_routes.id"), nullable=False, comment="工艺路线ID")
    node_id: Mapped[int] = mapped_column(ForeignKey("process_nodes.id"), nullable=False, comment="工艺节点ID")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序值")
    node_params_json: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), nullable=True, comment="节点参数JSON")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class ProcessRouteVersion(TimestampMixin, SoftDeleteMixin, Base):
    """工艺路线版本快照。"""

    __tablename__ = "process_route_versions"
    __table_args__ = (
        Index("idx_process_route_versions_route_id", "route_id"),
        Index("idx_process_route_versions_version_no", "version_no"),
        Index("idx_process_route_versions_is_deleted", "is_deleted"),
        {"comment": "工艺路线版本快照"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    route_id: Mapped[int] = mapped_column(ForeignKey("process_routes.id"), nullable=False, comment="工艺路线ID")
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="版本序号")
    snapshot_json: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), nullable=False, comment="路线快照JSON")
    change_log: Mapped[str | None] = mapped_column(Text, nullable=True, comment="变更说明")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="创建人ID，关联users.id")
