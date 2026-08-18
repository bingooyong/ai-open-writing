"""仓储层:唯一 SQL 入口(Spec §4)。业务/工作流代码不得裸写 SQL。"""

from novel_agent.domain.repos.annals import AnnalsRepo
from novel_agent.domain.repos.bible import BibleRepo
from novel_agent.domain.repos.canon import CanonRepo
from novel_agent.domain.repos.ops import OpsRepo
from novel_agent.domain.repos.planning import PlanningRepo
from novel_agent.domain.repos.production import ProductionRepo

__all__ = ["AnnalsRepo", "BibleRepo", "CanonRepo", "OpsRepo", "PlanningRepo", "ProductionRepo"]
