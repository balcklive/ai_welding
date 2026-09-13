"""dashboard 域路由（Task 8）：三个总览端点。

三个端点均需登录（router 级 `Depends(get_current_user)`），返回统一 `ok(...)` 信封。
业务聚合查询在 `app.services.dashboard`。`/api/v1` 前缀由 main.py 挂载时统一添加。
"""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_current_user
from app.core.db import get_session
from app.schemas.common import ok
from app.services import dashboard as svc

router = APIRouter(prefix="/dashboard", dependencies=[Depends(get_current_user)])


@router.get("/stats")
def get_stats(session: Session = Depends(get_session)) -> dict:
    """统计卡：数据总量 / 厂商总量 / 单条最大容量 / 已标注样本 + 完成度。"""
    return ok(svc.get_stats(session))


@router.get("/attributes")
def get_attributes(session: Session = Depends(get_session)) -> dict:
    """属性面板：焊机种类 / 缺陷种类 / 多模态种类 / 采集频率档位。"""
    return ok(svc.get_attributes(session))


@router.get("/distributions")
def get_distributions(session: Session = Depends(get_session)) -> dict:
    """分布图：厂商比重 / 过渡类型 / 焊接类型 / 缺陷分布 / 厂商词云。"""
    return ok(svc.get_distributions(session))

