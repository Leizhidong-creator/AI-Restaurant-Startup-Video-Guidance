from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from yongge_online.core.errors import NotFoundError
from yongge_online.db.models import Store, User
from yongge_online.profiles.schemas import StoreCreate, StoreUpdate, UserCreate


class ProfileService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_user(self, payload: UserCreate) -> User:
        user = User(
            id=str(uuid4()),
            display_name=payload.display_name,
            phone=payload.phone,
            experience_level=payload.experience_level.value,
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def get_user(self, user_id: str) -> User:
        user = await self.session.get(User, user_id)
        if user is None:
            raise NotFoundError("用户")
        return user

    async def create_store(self, user_id: str, payload: StoreCreate) -> Store:
        await self.get_user(user_id)
        store = Store(
            id=str(uuid4()),
            user_id=user_id,
            **payload.model_dump(mode="python"),
        )
        store.stage = payload.stage.value
        self.session.add(store)
        await self.session.commit()
        await self.session.refresh(store)
        return store

    async def get_store(self, store_id: str) -> Store:
        store = await self.session.get(Store, store_id)
        if store is None:
            raise NotFoundError("门店")
        return store

    async def update_store(self, store_id: str, payload: StoreUpdate) -> Store:
        store = await self.get_store(store_id)
        changes = payload.model_dump(exclude_unset=True, mode="python")
        if payload.stage is not None:
            changes["stage"] = payload.stage.value
        for field, value in changes.items():
            setattr(store, field, value)
        await self.session.commit()
        await self.session.refresh(store)
        return store


