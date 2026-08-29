from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from yongge_online.api.dependencies import get_db_session
from yongge_online.profiles.schemas import (
    StoreCreate,
    StoreRead,
    StoreUpdate,
    UserCreate,
    UserRead,
)
from yongge_online.profiles.service import ProfileService

router = APIRouter(prefix="/api/v1", tags=["profiles"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, session: DbSession) -> UserRead:
    user = await ProfileService(session).create_user(payload)
    return UserRead.model_validate(user)


@router.get("/users/{user_id}", response_model=UserRead)
async def get_user(user_id: str, session: DbSession) -> UserRead:
    user = await ProfileService(session).get_user(user_id)
    return UserRead.model_validate(user)


@router.post(
    "/users/{user_id}/stores",
    response_model=StoreRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_store(user_id: str, payload: StoreCreate, session: DbSession) -> StoreRead:
    store = await ProfileService(session).create_store(user_id, payload)
    return StoreRead.model_validate(store)


@router.get("/stores/{store_id}", response_model=StoreRead)
async def get_store(store_id: str, session: DbSession) -> StoreRead:
    store = await ProfileService(session).get_store(store_id)
    return StoreRead.model_validate(store)


@router.patch("/stores/{store_id}", response_model=StoreRead)
async def update_store(store_id: str, payload: StoreUpdate, session: DbSession) -> StoreRead:
    store = await ProfileService(session).update_store(store_id, payload)
    return StoreRead.model_validate(store)


