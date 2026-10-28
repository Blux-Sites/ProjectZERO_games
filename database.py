from datetime import datetime, timezone
from sqlalchemy import select, func, inspect, text, Integer, String, Float, Text, DateTime, ForeignKey, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column, relationship, DeclarativeBase, sessionmaker, selectinload

engine = create_engine("sqlite:///shop.db")
SessionLocal = sessionmaker(bind=engine, autoflush=False)

ORDER_STATUSES = ["New", "Processing", "Shipped", "Completed", "Cancelled"]

DEFAULT_COVERS = {
    "Starfall Drifters": "covers/starfall-drifters.svg",
    "Crown of Ash": "covers/crown-of-ash.svg",
    "Tiny Tavern": "covers/tiny-tavern.svg",
    "Redline Rivals": "covers/redline-rivals.svg",
    "Hollow Manor": "covers/hollow-manor.svg",
    "Pocket Kingdoms": "covers/pocket-kingdoms.svg",
}


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    email: Mapped[str] = mapped_column(String(120), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    genre: Mapped[str] = mapped_column(String(40), default="Other")
    platform: Mapped[str] = mapped_column(String(40), default="PC")
    price: Mapped[float] = mapped_column(Float)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    image: Mapped[str] = mapped_column(String(255), default="")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    full_name: Mapped[str] = mapped_column(String(100))
    address: Mapped[str] = mapped_column(String(255))
    total: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="New")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    user: Mapped["User"] = relationship()


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(100))
    price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer)

    order: Mapped["Order"] = relationship(back_populates="items")

    @property
    def subtotal(self):
        return round(self.price * self.quantity, 2)


def init_db():
    Base.metadata.create_all(bind=engine)
    columns = [column["name"] for column in inspect(engine).get_columns("products")]
    if "image" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE products ADD COLUMN image VARCHAR(255) NOT NULL DEFAULT ''"))
    with SessionLocal() as db:
        if db.scalars(select(Product)).first() is None:
            db.add_all([
                Product(name="Starfall Drifters", genre="Action", platform="PC", price=39.99, stock=25,
                        description="Fast space combat. Fly, loot and upgrade your ship."),
                Product(name="Crown of Ash", genre="RPG", platform="PlayStation", price=59.99, stock=12,
                        description="A 60-hour fantasy story where every choice changes the kingdom."),
                Product(name="Tiny Tavern", genre="Strategy", platform="Switch", price=24.99, stock=30,
                        description="Run a cozy tavern, hire staff and keep the guests happy."),
                Product(name="Redline Rivals", genre="Racing", platform="Xbox", price=49.99, stock=0,
                        description="Street racing with 80 cars and online ranked seasons."),
                Product(name="Hollow Manor", genre="Horror", platform="PC", price=19.99, stock=18,
                        description="Explore a haunted house. Short, tense and best played at night."),
                Product(name="Pocket Kingdoms", genre="Puzzle", platform="Switch", price=14.99, stock=40,
                        description="Relaxing puzzle game with over 300 handmade levels."),
            ])
            db.commit()
        for product in db.scalars(select(Product).where(Product.image == "")):
            if product.name in DEFAULT_COVERS:
                product.image = DEFAULT_COVERS[product.name]
        db.commit()


def get_user_by_email(email: str):
    with SessionLocal() as db:
        return db.scalars(select(User).where(User.email == email)).first()


def get_user_by_username(username: str):
    with SessionLocal() as db:
        return db.scalars(select(User).where(User.username == username)).first()


def create_user(username: str, email: str, password_hash: str):
    with SessionLocal() as db:
        user = User(username=username, email=email, password_hash=password_hash)
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return None
        db.refresh(user)
        return user


def get_user_by_id(user_id: int):
    with SessionLocal() as db:
        return db.get(User, user_id)


def get_featured_products(limit: int = 3):
    with SessionLocal() as db:
        return list(db.scalars(select(Product).order_by(Product.id.desc()).limit(limit)))


def get_all_products(genre: str | None = None):
    with SessionLocal() as db:
        query = select(Product).order_by(Product.name)
        if genre:
            query = query.where(Product.genre == genre)
        return list(db.scalars(query))


def get_genres():
    with SessionLocal() as db:
        return list(db.scalars(select(Product.genre).distinct().order_by(Product.genre)))


def get_platforms():
    with SessionLocal() as db:
        return list(db.scalars(select(Product.platform).distinct().order_by(Product.platform)))


def get_product(product_id: int):
    with SessionLocal() as db:
        return db.get(Product, product_id)


def get_products_by_ids(ids: list[int]):
    if not ids:
        return []
    with SessionLocal() as db:
        return list(db.scalars(select(Product).where(Product.id.in_(ids))))


def create_product(data: dict):
    with SessionLocal() as db:
        product = Product(**data)
        db.add(product)
        db.commit()
        db.refresh(product)
        return product


def update_product(product_id: int, data: dict):
    with SessionLocal() as db:
        product = db.get(Product, product_id)
        if product is None:
            return False
        for key, value in data.items():
            setattr(product, key, value)
        db.commit()
        return True


def delete_product(product_id: int):
    with SessionLocal() as db:
        product = db.get(Product, product_id)
        if product is None:
            return False
        db.delete(product)
        db.commit()
        return True


def create_order(user_id: int, full_name: str, address: str, cart: dict[int, int]):
    with SessionLocal() as db:
        order = Order(user_id=user_id, full_name=full_name, address=address, total=0.0, status="New")
        total = 0.0
        for product_id, quantity in cart.items():
            product = db.get(Product, product_id)
            if product is None:
                return None, "A product in your cart is no longer available."
            if quantity < 1 or quantity > product.stock:
                return None, f"Not enough stock for {product.name}. Available: {product.stock}."
            product.stock -= quantity
            total += product.price * quantity
            order.items.append(OrderItem(product_id=product.id, name=product.name,
                                         price=product.price, quantity=quantity))
        order.total = round(total, 2)
        db.add(order)
        db.commit()
        return order.id, None


def get_order(order_id: int):
    with SessionLocal() as db:
        query = (select(Order).where(Order.id == order_id)
                 .options(selectinload(Order.items), selectinload(Order.user)))
        return db.scalars(query).first()


def get_orders_for_user(user_id: int):
    with SessionLocal() as db:
        query = (select(Order).where(Order.user_id == user_id).order_by(Order.id.desc())
                 .options(selectinload(Order.items)))
        return list(db.scalars(query))


def get_all_orders(status: str | None = None):
    with SessionLocal() as db:
        query = (select(Order).order_by(Order.id.desc())
                 .options(selectinload(Order.items), selectinload(Order.user)))
        if status:
            query = query.where(Order.status == status)
        return list(db.scalars(query))


def set_order_status(order_id: int, status: str):
    if status not in ORDER_STATUSES:
        return "Unknown status."
    with SessionLocal() as db:
        query = select(Order).where(Order.id == order_id).options(selectinload(Order.items))
        order = db.scalars(query).first()
        if order is None:
            return "Order not found."
        if order.status == "Cancelled":
            return "A cancelled order cannot be changed."
        if status == "Cancelled":
            for item in order.items:
                product = db.get(Product, item.product_id) if item.product_id else None
                if product is not None:
                    product.stock += item.quantity
        order.status = status
        db.commit()
        return None


def get_stats():
    with SessionLocal() as db:
        revenue = db.scalar(select(func.coalesce(func.sum(Order.total), 0.0)).where(Order.status != "Cancelled"))
        return {
            "products": db.scalar(select(func.count(Product.id))),
            "orders": db.scalar(select(func.count(Order.id))),
            "new_orders": db.scalar(select(func.count(Order.id)).where(Order.status == "New")),
            "users": db.scalar(select(func.count(User.id))),
            "out_of_stock": db.scalar(select(func.count(Product.id)).where(Product.stock <= 0)),
            "revenue": round(revenue, 2),
        }