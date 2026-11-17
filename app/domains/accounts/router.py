from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Request, Response

from app.domains.accounts.models import Credentials, PasswordChange, User, UserCreate, UserUpdate
from app.domains.accounts.service import COOKIE_NAME, SESSION_SECONDS, AccountService

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"], route_class=DishkaRoute)


@router.post("/login")
async def login(
    data: Credentials, request: Request, response: Response, service: FromDishka[AccountService]
) -> User:
    user, token = await service.login(
        data,
        request.client.host if request.client else "unknown",
        request.cookies.get(COOKIE_NAME, ""),
    )
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return user


@router.get("/me")
async def me(request: Request) -> User:
    return User.model_validate(request.state.user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, service: FromDishka[AccountService]) -> None:
    await service.logout(request.cookies.get(COOKIE_NAME, ""))
    response.delete_cookie(COOKIE_NAME, path="/")


@router.post("/password", status_code=204)
async def password(
    data: PasswordChange, request: Request, response: Response, service: FromDishka[AccountService]
) -> None:
    await service.change_password(request.state.user, data)
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/users")
async def users(service: FromDishka[AccountService]) -> list[User]:
    return await service.find()


@router.post("/users", status_code=201)
async def create_user(data: UserCreate, service: FromDishka[AccountService]) -> User:
    return await service.create(data)


@router.patch("/users/{user_id}")
async def update_user(
    user_id: UUID, data: UserUpdate, request: Request, service: FromDishka[AccountService]
) -> User:
    return await service.update(user_id, data, request.state.user)
