"""正史增量 CanonDelta(PRD §2.12 YAML 全字段;落表映射见 Spec §5)。"""

from pydantic import Field

from novel_agent.domain.schemas.base import EntityStateType, VersionedSchema


class EntityStateChange(VersionedSchema):
    """→ entity_state 表(Spec §5 映射)。"""

    entity_id: str = Field(min_length=1, description="角色/地点/物件标识")
    state_type: EntityStateType
    old_value: str = Field(default="", description="变更前(空=新增)")
    new_value: str = Field(min_length=1)
    reason: str = Field(min_length=1, description="来源事件")


class RelationshipChange(VersionedSchema):
    """→ relationship_state 表。关系变化必须对应事件(PRD §2.6)。"""

    parties: list[str] = Field(min_length=2, max_length=2)
    from_state: str = Field(min_length=1)
    to_state: str = Field(min_length=1)
    evidence: str = Field(min_length=1, description="触发事件/代价")


class ThreadUpdate(VersionedSchema):
    """→ plot_thread 表(伏笔线状态迁移)。"""

    thread_id: str = Field(min_length=1)
    note: str = Field(min_length=1)


class CanonDelta(VersionedSchema):
    """每章正史增量提案:仅 Canon Curator 产出,批准后由 CanonWriter 单事务提交。"""

    chapter_key: str = Field(min_length=1)
    base_canon_version: str = Field(min_length=1, description="基于的 canon 快照版本")
    new_facts: list[EntityStateChange] = Field(default_factory=list)
    character_state_changes: list[EntityStateChange] = Field(default_factory=list)
    relationship_changes: list[RelationshipChange] = Field(default_factory=list)
    knowledge_changes: list[EntityStateChange] = Field(default_factory=list)
    resource_changes: list[EntityStateChange] = Field(default_factory=list)
    timeline_events: list[str] = Field(
        default_factory=list,
        description="阶段0 仅存原始记录,不参与结构化冲突校验(Spec §5)",
    )
    foreshadowing_created: list[ThreadUpdate] = Field(default_factory=list)
    foreshadowing_progressed: list[ThreadUpdate] = Field(default_factory=list)
    foreshadowing_resolved: list[ThreadUpdate] = Field(default_factory=list)
    world_rule_proposals: list[str] = Field(
        default_factory=list, description="→ project.world_rules(带变更记录)"
    )
