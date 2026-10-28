import math
import os
import uuid
from functools import wraps

from flask import Flask, Blueprint, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash
import database as db


ADMIN_SLUG = os.environ.get("SHOP_ADMIN_SLUG", "167623").strip("/") or "167623"
ALLOWED_IMAGE_TYPES = {"png", "jpg", "jpeg", "webp", "gif"}

app = Flask(__name__)
app.secret_key = "sajdhsakhjfdsi834472mdsajdh"
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  MAX_CONTENT_LENGTH=5 * 1024 * 1024)

UPLOAD_DIR = os.path.join(app.static_folder, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

db.init_db()


@app.context_processor
def inject_globals():
    user_id = session.get("user_id")
    return {
        "current_user": db.get_user_by_id(user_id) if user_id else None,
        "cart_count": sum(get_cart().values()),
        "is_admin": bool(session.get("is_admin")),
    }


def get_cart():
    raw = session.get("cart", {})
    cart = {}
    for key, value in raw.items():
        try:
            cart[int(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return cart


def save_cart(cart):
    session["cart"] = {str(key): value for key, value in cart.items()}


def build_cart():
    cart = get_cart()
    products = {p.id: p for p in db.get_products_by_ids(list(cart))}
    lines = []
    total = 0.0
    for product_id, quantity in cart.items():
        product = products.get(product_id)
        if product is None:
            continue
        subtotal = round(product.price * quantity, 2)
        lines.append({"product": product, "quantity": quantity, "subtotal": subtotal})
        total += subtotal
    return lines, round(total, 2)


def parse_quantity(value, default=1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper


@app.route("/")
def home():
    return render_template("home.html", products=db.get_featured_products())


@app.route("/products")
def products():
    genre = request.args.get("genre") or None
    return render_template(
        "products.html",
        products=db.get_all_products(genre),
        genres=db.get_genres(),
        active_genre=genre,
    )


@app.route("/product/<int:product_id>")
def product_detail(product_id):
    product = db.get_product(product_id)
    if product is None:
        abort(404)
    return render_template("product.html", product=product)


@app.route("/cart")
def cart():
    lines, total = build_cart()
    return render_template("cart.html", lines=lines, total=total)


@app.route("/cart/add/<int:product_id>", methods=["POST"])
def cart_add(product_id):
    product = db.get_product(product_id)
    if product is None:
        abort(404)
    if product.stock <= 0:
        flash("This game is out of stock.", "error")
        return redirect(url_for("product_detail", product_id=product_id))
    cart_data = get_cart()
    quantity = max(1, parse_quantity(request.form.get("quantity")))
    new_quantity = cart_data.get(product_id, 0) + quantity
    if new_quantity > product.stock:
        new_quantity = product.stock
        flash(f"Only {product.stock} copies of {product.name} are available.", "error")
    else:
        flash(f"{product.name} added to your cart.", "success")
    cart_data[product_id] = new_quantity
    save_cart(cart_data)
    return redirect(url_for("cart"))


@app.route("/cart/update/<int:product_id>", methods=["POST"])
def cart_update(product_id):
    cart_data = get_cart()
    if product_id in cart_data:
        quantity = parse_quantity(request.form.get("quantity"), cart_data[product_id])
        product = db.get_product(product_id)
        if quantity <= 0 or product is None:
            cart_data.pop(product_id, None)
        else:
            if quantity > product.stock:
                quantity = product.stock
                flash(f"Only {product.stock} copies of {product.name} are available.", "error")
            if quantity <= 0:
                cart_data.pop(product_id, None)
            else:
                cart_data[product_id] = quantity
        save_cart(cart_data)
    return redirect(url_for("cart"))


@app.route("/cart/remove/<int:product_id>", methods=["POST"])
def cart_remove(product_id):
    cart_data = get_cart()
    cart_data.pop(product_id, None)
    save_cart(cart_data)
    return redirect(url_for("cart"))


@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    lines, total = build_cart()
    if not lines:
        flash("Your cart is empty.", "error")
        return redirect(url_for("cart"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        address = request.form.get("address", "").strip()

        error = None
        if len(full_name) < 2 or len(full_name) > 100:
            error = "Please enter your full name."
        elif len(address) < 5 or len(address) > 255:
            error = "Please enter a valid delivery address."

        if error:
            flash(error, "error")
            return render_template("checkout.html", lines=lines, total=total,
                                   full_name=full_name, address=address)

        cart_data = {line["product"].id: line["quantity"] for line in lines}
        order_id, order_error = db.create_order(session["user_id"], full_name, address, cart_data)
        if order_error:
            flash(order_error, "error")
            return redirect(url_for("cart"))

        session.pop("cart", None)
        flash("Your order has been placed. Thank you!", "success")
        return redirect(url_for("order_detail", order_id=order_id))

    return render_template("checkout.html", lines=lines, total=total, full_name="", address="")


@app.route("/orders")
@login_required
def orders():
    return render_template("orders.html", orders=db.get_orders_for_user(session["user_id"]))


@app.route("/orders/<int:order_id>")
@login_required
def order_detail(order_id):
    order = db.get_order(order_id)
    if order is None or order.user_id != session["user_id"]:
        abort(404)
    return render_template("order.html", order=order)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        error = None
        if len(username) < 3:
            error = "Username must be at least 3 characters long."
        elif len(password) < 6:
            error = "Password must be at least 6 characters long."
        elif password != confirm:
            error = "Passwords do not match."
        elif db.get_user_by_email(email):
            error = "A user with this email already exists."
        elif db.get_user_by_username(username):
            error = "This username is already taken."

        if error is None:
            user = db.create_user(username, email, generate_password_hash(password))
            if user is None:
                error = "A user with these details already exists."

        if error:
            flash(error, "error")
            return render_template("register.html", username=username, email=email)

        flash("Registration successful! You can now log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = db.get_user_by_email(email)
        if user is None or not check_password_hash(user.password_hash, password):
            flash("Invalid email or password.", "error")
            return render_template("login.html", email=email)

        session["user_id"] = user.id
        flash("You are logged in.", "success")
        return redirect(url_for("home"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("You are logged out.", "success")
    return redirect(url_for("home"))


admin = Blueprint("admin", __name__, url_prefix=f"/admin/{ADMIN_SLUG}")


@admin.before_request
def unlock_admin():
    session["is_admin"] = True


def save_image(file):
    if file is None or not file.filename:
        return "", None
    extension = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if extension not in ALLOWED_IMAGE_TYPES:
        return "", "Image must be a PNG, JPG, WEBP or GIF file."
    filename = f"{uuid.uuid4().hex}.{extension}"
    file.save(os.path.join(UPLOAD_DIR, filename))
    return f"uploads/{filename}", None


def remove_image_file(image):
    if image and image.startswith("uploads/"):
        try:
            os.remove(os.path.join(app.static_folder, image))
        except OSError:
            pass


@app.errorhandler(413)
def too_large(error):
    return "The uploaded file is too large. The maximum size is 5 MB.", 413


def product_values(product=None):
    if product is None:
        return {"name": "", "description": "", "genre": "", "platform": "", "price": "", "stock": "0"}
    return {
        "name": product.name,
        "description": product.description,
        "genre": product.genre,
        "platform": product.platform,
        "price": f"{product.price:.2f}",
        "stock": str(product.stock),
    }


def parse_product_form(form):
    name = form.get("name", "").strip()
    description = form.get("description", "").strip()
    genre = form.get("genre", "").strip() or "Other"
    platform = form.get("platform", "").strip() or "PC"

    try:
        price = round(float(form.get("price", "")), 2)
    except ValueError:
        return None, "Price must be a number."
    try:
        stock = int(form.get("stock", ""))
    except ValueError:
        return None, "Stock must be a whole number."

    if not name or len(name) > 100:
        return None, "Name is required and must be at most 100 characters."
    if len(genre) > 40 or len(platform) > 40:
        return None, "Genre and platform must be at most 40 characters."
    if not math.isfinite(price) or price < 0:
        return None, "Price must be zero or greater."
    if stock < 0:
        return None, "Stock must be zero or greater."

    data = {"name": name, "description": description, "genre": genre,
            "platform": platform, "price": price, "stock": stock}
    return data, None


@admin.route("/")
def index():
    return render_template("admin/dashboard.html", stats=db.get_stats(),
                           orders=db.get_all_orders()[:5])


@admin.route("/logout")
def logout():
    session.pop("is_admin", None)
    flash("You are logged out of the admin panel.", "success")
    return redirect(url_for("home"))


@admin.route("/products")
def products():
    return render_template("admin/products.html", products=db.get_all_products())


@admin.route("/products/new", methods=["GET", "POST"])
def product_new():
    values = product_values()
    if request.method == "POST":
        data, error = parse_product_form(request.form)
        image = ""
        if error is None:
            image, error = save_image(request.files.get("image"))
        if error:
            flash(error, "error")
            values = dict(request.form)
        else:
            data["image"] = image
            product = db.create_product(data)
            flash(f"{product.name} was added.", "success")
            return redirect(url_for("admin.products"))
    return render_template("admin/product_form.html", values=values, heading="Add a new game",
                           current_image="", genres=db.get_genres(), platforms=db.get_platforms())


@admin.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
def product_edit(product_id):
    product = db.get_product(product_id)
    if product is None:
        abort(404)
    values = product_values(product)
    if request.method == "POST":
        data, error = parse_product_form(request.form)
        new_image = ""
        if error is None:
            new_image, error = save_image(request.files.get("image"))
        if error:
            flash(error, "error")
            values = dict(request.form)
        else:
            if new_image:
                data["image"] = new_image
                remove_image_file(product.image)
            elif request.form.get("remove_image"):
                data["image"] = ""
                remove_image_file(product.image)
            db.update_product(product_id, data)
            flash(f"{data['name']} was updated.", "success")
            return redirect(url_for("admin.products"))
    return render_template("admin/product_form.html", values=values, heading=f"Edit {product.name}",
                           current_image=product.image, genres=db.get_genres(), platforms=db.get_platforms())


@admin.route("/products/<int:product_id>/delete", methods=["POST"])
def product_delete(product_id):
    product = db.get_product(product_id)
    if product is not None and db.delete_product(product_id):
        remove_image_file(product.image)
        flash("The game was deleted.", "success")
    else:
        flash("Game not found.", "error")
    return redirect(url_for("admin.products"))


@admin.route("/orders")
def orders():
    status = request.args.get("status") or None
    if status not in db.ORDER_STATUSES:
        status = None
    return render_template("admin/orders.html", orders=db.get_all_orders(status),
                           statuses=db.ORDER_STATUSES, active_status=status)


@admin.route("/orders/<int:order_id>")
def order_detail(order_id):
    order = db.get_order(order_id)
    if order is None:
        abort(404)
    return render_template("admin/order.html", order=order, statuses=db.ORDER_STATUSES)


@admin.route("/orders/<int:order_id>/status", methods=["POST"])
def order_status(order_id):
    error = db.set_order_status(order_id, request.form.get("status", ""))
    if error:
        flash(error, "error")
    else:
        flash("Order status updated.", "success")
    return redirect(url_for("admin.order_detail", order_id=order_id))


app.register_blueprint(admin)


if __name__ == "__main__":
    with app.test_request_context():
        print(f"Admin panel: http://127.0.0.1:5000{url_for('admin.index')}")
    app.run(debug=True)