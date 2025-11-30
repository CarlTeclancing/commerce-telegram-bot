BOT_TOKEN = "BOT_TOKEN_HERE"

import os
import json
import logging
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import BadRequest

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# Global in-memory datastore loaded from data.json
DATA: dict = {}


def load_data():
    """Load configuration and catalog from data.json.
    Also tolerates accidental Markdown code fences by stripping them.
    """
    global DATA
    path = os.path.join(os.getcwd(), 'data.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = f.read().strip()
            # Strip surrounding code fences if present
            if raw.startswith('```'):
                # remove first fence line
                first_newline = raw.find('\n')
                if first_newline != -1:
                    raw = raw[first_newline + 1:]
                # remove trailing ``` if present
                if raw.endswith('```'):
                    raw = raw[:-3].strip()
            DATA = json.loads(raw)
            logger.info('Loaded data.json successfully')
    except Exception as e:
        logger.exception(f'Failed to load data.json: {e}')
        # Safe defaults
        DATA = {
            'bot': {
                'payment': {
                    'btc': 'N/A',
                    'usdt_trc20': 'N/A'
                },
                'placeholders': {
                    'product_image': 'https://via.placeholder.com/640x360.png?text=Product'
                }
            },
            'countries': [],
            'faq': [],
            'how_it_works': [],
            'reviews': {},
            'categories': {}
        }


# Identity and logging helpers

def _get_user_identity(update: Update):
    user = update.effective_user
    user_id = getattr(user, 'id', None)
    username = getattr(user, 'username', None)
    if username:
        user_key = str(username).lower()
        name = username
    else:
        name = (getattr(user, 'first_name', '') or '') + ((' ' + getattr(user, 'last_name', '')) if getattr(user, 'last_name', None) else '')
        name = name.strip() or None
        user_key = (name.replace(' ', '_') if name else f"id_{user_id}")
    return user_key, user_id, username or name


def _log_user_action(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str, details=None):
    try:
        user_key, user_id, username = _get_user_identity(update)
        sessions = context.bot_data.setdefault('sessions', {})
        if user_key not in sessions:
            sessions[user_key] = {
                'user_id': user_id,
                'username': username,
                'start_time': datetime.utcnow().isoformat() + 'Z',
                'actions': []
            }
        sessions[user_key]['actions'].append({
            'time': datetime.utcnow().isoformat() + 'Z',
            'action': action,
            'details': details or {}
        })
        logger.info(f"Session log for {user_key}: {action} {details or ''}")
    except Exception:
        logger.exception("Failed to log user action")


# Keyboards and UI builders

def main_menu(user_key: str = '', bot_data: dict | None = None):
    if bot_data is None:
        bot_data = {}
    cart_count = len(bot_data.get("cart", {}).get(user_key, []))
    orders_count = len(bot_data.get("orders", {}).get(user_key, []))
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤔 How does it work?", callback_data="how_it_works")],
        [InlineKeyboardButton("✋ Help", callback_data="help"),
         InlineKeyboardButton("📘 User Guide", callback_data="user_guide")],
        [InlineKeyboardButton("🎁 Products", callback_data="products")],
        [InlineKeyboardButton("📊 Reviews", callback_data="reviews"),
         InlineKeyboardButton("📢 Ref & Earn", callback_data="ref_earn")],
        [InlineKeyboardButton("🏷 Coupon", callback_data="coupon"),
         InlineKeyboardButton("❤️ Friendly Services", callback_data="friendly_services")],
        [InlineKeyboardButton("❓ FAQs", callback_data="faqs")],
        [InlineKeyboardButton(f"🛒 Cart ({cart_count})", callback_data="cart"),
         InlineKeyboardButton(f"📦 Orders ({orders_count})", callback_data="orders")]
    ])


def get_country_keyboard():
    countries = DATA.get('countries', [])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(c, callback_data=f"country_{c.replace(' ', '_')}")] for c in countries
    ])


def get_products_keyboard():
    categories = DATA.get('categories', {})
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(cat_info["name"], callback_data=f"category_{cat_key}")]
        for cat_key, cat_info in categories.items()
    ] + [[InlineKeyboardButton("⬅️ Back to Menu", callback_data="main_menu")]])


def get_subcategories_keyboard(category_key):
    category = DATA.get('categories', {}).get(category_key, {})
    subcats = category.get("subcategories", {})
    keyboard = [
        [InlineKeyboardButton(sub["name"], callback_data=f"subcategory|{category_key}|{sub_key}")]
        for sub_key, sub in subcats.items()
    ]
    keyboard.append([InlineKeyboardButton("⬅️ Back to Products", callback_data="products")])
    return InlineKeyboardMarkup(keyboard)


def get_product_keyboard(category_key, sub_key):
    subcat = DATA['categories'][category_key]["subcategories"][sub_key]
    products = subcat.get("products", {})
    keyboard = [
        [InlineKeyboardButton(prod_info["name"], callback_data=f"product|{category_key}|{sub_key}|{prod_key}")]
        for prod_key, prod_info in products.items()
    ]
    keyboard.append([InlineKeyboardButton("⬅️ Back to Subcategories", callback_data=f"category_{category_key}")])
    return InlineKeyboardMarkup(keyboard)


def get_quantity_keyboard(category_key, sub_key, product_key):
    product = DATA['categories'][category_key]["subcategories"][sub_key]["products"][product_key]
    quantities = product.get("quantities", {})
    keyboard = []

    if isinstance(quantities, dict):
        for qty, price in quantities.items():
            keyboard.append([
                InlineKeyboardButton(f"{qty} - {price}", callback_data=f"quantity|{category_key}|{sub_key}|{product_key}|{qty}")
            ])
    else:
        for qty in quantities:
            keyboard.append([
                InlineKeyboardButton(str(qty), callback_data=f"quantity|{category_key}|{sub_key}|{product_key}|{qty}")
            ])

    keyboard.append([
        InlineKeyboardButton("✏️ Enter Custom Quantity", callback_data=f"custom_qty|{category_key}|{sub_key}|{product_key}")
    ])
    keyboard.append([
        InlineKeyboardButton("⬅️ Back to Products", callback_data=f"subcategory|{category_key}|{sub_key}")
    ])
    return InlineKeyboardMarkup(keyboard)


def get_payment_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Pay with BTC", callback_data="pay_btc")],
        [InlineKeyboardButton("Pay with USDT", callback_data="pay_usdt")],
        [InlineKeyboardButton("⬅️ Back to Menu", callback_data="main_menu")]
    ])


# Reviews and images

def _get_product_image(product: dict) -> str:
    # Prefer explicit image field if present
    image = product.get("image") if isinstance(product, dict) else None
    if image:
        return image
    # Try a default local file if it exists
    local_path = os.path.join(os.getcwd(), 'img', 'img1010.jpg')
    if os.path.exists(local_path):
        return local_path
    # Fallback to a placeholder URL from config
    return DATA.get('bot', {}).get('placeholders', {}).get('product_image', 'https://via.placeholder.com/640x360.png?text=Product')


def get_all_reviews():
    reviews = DATA.get('reviews', {})
    logger.info(f"REVIEWS dictionary: {reviews}")
    if not reviews:
        logger.warning("REVIEWS dictionary is empty.")
        return "No reviews available at the moment."

    review_texts = []
    try:
        for product, reviews_list in reviews.items():
            review_texts.append(f"📦 *{product.replace('_', ' ').title()}* Reviews:\n")
            if isinstance(reviews_list, list):
                for review in reviews_list:
                    if isinstance(review, dict) and "stars" in review and "text" in review:
                        stars = "⭐" * int(review["stars"])
                        review_texts.append(f"\n{stars} {review['text']}")
                    else:
                        logger.error(f"Malformed review item for product {product}: {review}")
                        review_texts.append("\n_Error displaying this review_")
            else:
                logger.error(f"Malformed reviews list for product {product}: {reviews_list}")
                review_texts.append(f"\n_Error displaying reviews for {product}_")
            review_texts.append("")  # blank line between products
    except Exception as e:
        logger.error(f"Error in get_all_reviews: {e}", exc_info=True)
        return "An error occurred while fetching reviews."

    logger.info(f"Generated review text: {review_texts}")
    if not review_texts:
        return "No reviews found."
    return "\n".join(review_texts)


# Cart / Pricing helpers

def _parse_price_value(price_raw):
    try:
        if isinstance(price_raw, (int, float)):
            return float(price_raw)
        s = str(price_raw)
        s = s.replace('€', '').replace('/unit', '').replace(',', '').strip()
        parts = s.split()
        num = parts[0]
        return float(num)
    except Exception:
        logger.exception(f"Failed to parse price: {price_raw}")
        return 0.0


def _cart_summary_and_total(bot_data, user_key):
    items = bot_data.get('cart', {}).get(user_key, [])
    lines = []
    total = 0.0
    for it in items:
        try:
            if 'product' in it and 'qty' in it and 'price' in it:
                price_val = _parse_price_value(it['price'])
                lines.append(f"- {it['qty']} of {it['product']} @ {it['price']}")
                total += price_val
            elif 'category' in it and 'product' in it and 'quantity' in it:
                cat = it['category']
                sub = it.get('subcategory')
                prod_key = it['product']
                qty = it['quantity']
                prod = DATA.get('categories', {}).get(cat, {}).get('subcategories', {}).get(sub, {}).get('products', {}).get(prod_key, {})
                if prod:
                    price_raw = None
                    quantities = prod.get('quantities')
                    if isinstance(quantities, dict) and qty in quantities:
                        price_raw = quantities[qty]
                    else:
                        price_raw = prod.get('price')
                    price_val = _parse_price_value(price_raw)
                    lines.append(f"- {qty} of {prod.get('name','Unknown')} @ {price_raw}")
                    total += price_val
                else:
                    lines.append(f"- {qty} of {prod_key} @ Unknown price")
            else:
                lines.append(f"- {it}")
        except Exception as e:
            logger.exception(f"Error summarizing cart item {it}: {e}")
            lines.append(f"- Error displaying item: {it}")
    return lines, total


# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _log_user_action(update, context, 'start')
    await update.message.reply_text(
        "🌍 Please select your country:",
        reply_markup=get_country_keyboard()
    )


async def reviews_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_key, _, _ = _get_user_identity(update)
    _log_user_action(update, context, 'view_reviews')
    await update.message.reply_text(
        get_all_reviews(),
        parse_mode="Markdown",
        reply_markup=main_menu(user_key, context.bot_data)
    )


async def faqs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_key, _, _ = _get_user_identity(update)
    _log_user_action(update, context, 'view_faqs')
    faq_text = "\n\n".join(DATA.get('faq', []))
    await update.message.reply_text(
        faq_text,
        parse_mode="Markdown",
        reply_markup=main_menu(user_key, context.bot_data)
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_key, user_id, username = _get_user_identity(update)

    logger.info(f"Callback query received: {data} from user {user_key} ({user_id})")

    try:
        if data.startswith("country_"):
            country = data.split("_", 1)[1].replace('_', ' ')
            context.user_data["country"] = country
            _log_user_action(update, context, 'country_selected', {'country': country})
            await query.edit_message_text(
                text=f"✅ You selected *{country}*.\nHere is the main menu:",
                parse_mode="Markdown",
                reply_markup=main_menu(user_key, context.bot_data)
            )

        elif data == "main_menu":
            await query.edit_message_text(
                text="🏠 Main Menu:",
                reply_markup=main_menu(user_key, context.bot_data)
            )

        elif data == "how_it_works":
            how_text = "\n\n".join(DATA.get('how_it_works', []))
            await query.edit_message_text(
                how_text,
                parse_mode="Markdown",
                reply_markup=main_menu(user_key, context.bot_data)
            )

        elif data == "help":
            await query.edit_message_text(
                "Use /reviews to see product reviews, /faqs for FAQs, or navigate via the menu buttons.",
                reply_markup=main_menu(user_key, context.bot_data)
            )

        elif data == "user_guide":
            await query.edit_message_text(
                "User Guide:\n1) Choose your country\n2) Browse products\n3) Add to cart\n4) Checkout and pay\n5) Receive discreet delivery.",
                reply_markup=main_menu(user_key, context.bot_data)
            )

        elif data == "ref_earn":
            await query.edit_message_text(
                "Referral & Earn:\nShare your unique referral message to earn discounts on future orders.",
                reply_markup=main_menu(user_key, context.bot_data)
            )

        elif data == "coupon":
            await query.edit_message_text(
                "Coupons:\nGot a coupon? Apply it at checkout by sending it to support (coming soon).",
                reply_markup=main_menu(user_key, context.bot_data)
            )

        elif data == "friendly_services":
            await query.edit_message_text(
                "Friendly Services:\nWe provide fast replies, discreet shipping, and helpful support.",
                reply_markup=main_menu(user_key, context.bot_data)
            )

        elif data == "reviews":
            _log_user_action(update, context, 'view_reviews')
            reviews_text = get_all_reviews()
            try:
                await query.edit_message_text(
                    text=reviews_text,
                    parse_mode="Markdown",
                    reply_markup=main_menu(user_key, context.bot_data)
                )
            except BadRequest as e:
                logger.warning(f"Edit message failed for reviews: {e}")
                await query.edit_message_text(
                    text="Product reviews could not be displayed right now.",
                    reply_markup=main_menu(user_key, context.bot_data)
                )

        elif data == "faqs":
            faq_text = "\n\n".join(DATA.get('faq', []))
            await query.edit_message_text(
                faq_text,
                parse_mode="Markdown",
                reply_markup=main_menu(user_key, context.bot_data)
            )

        elif data == "products":
            await query.edit_message_text(
                text="🎁 Select a category:",
                reply_markup=get_products_keyboard()
            )

        elif data.startswith("category_"):
            category_key = data.split("_", 1)[1]
            await query.edit_message_text(
                text=f"📂 Subcategories under *{DATA['categories'][category_key]['name']}*:",
                parse_mode="Markdown",
                reply_markup=get_subcategories_keyboard(category_key)
            )

        elif data.startswith("subcategory|"):
            _, category_key, sub_key = data.split("|")
            await query.edit_message_text(
                text="🛍 Choose a product:",
                reply_markup=get_product_keyboard(category_key, sub_key)
            )

        elif data.startswith("product|"):
            _, category_key, sub_key, product_key = data.split("|")
            product = DATA['categories'][category_key]["subcategories"][sub_key]["products"][product_key]
            # Build caption with details and available quantities
            quantities = product.get("quantities", {})
            if isinstance(quantities, dict):
                avails = ", ".join([f"{k} ({v})" for k, v in quantities.items()])
            else:
                avails = ", ".join([str(q) for q in quantities])
            caption = (
                f"*{product.get('name','Product')}*\n\n"
                f"{product.get('description','No description available.')}\n\n"
                f"Available: {avails if avails else 'See options below.'}"
            )
            image = _get_product_image(product)
            placeholder = DATA.get('bot', {}).get('placeholders', {}).get('product_image', 'https://via.placeholder.com/640x360.png?text=Product')
            # Attempt to send the primary product image; on failure, send placeholder; finally fallback to text.
            sent_photo = False
            try:
                if isinstance(image, str) and os.path.isfile(image):
                    with open(image, 'rb') as f:
                        await query.message.reply_photo(
                            photo=f,
                            caption=caption,
                            parse_mode="Markdown",
                            reply_markup=get_quantity_keyboard(category_key, sub_key, product_key)
                        )
                        sent_photo = True
                else:
                    await query.message.reply_photo(
                        photo=image,
                        caption=caption,
                        parse_mode="Markdown",
                        reply_markup=get_quantity_keyboard(category_key, sub_key, product_key)
                    )
                    sent_photo = True
            except Exception as e:
                logger.warning(f"Failed to send product image '{image}': {e}. Trying placeholder...")
                # Try placeholder image once
                try:
                    await query.message.reply_photo(
                        photo=placeholder,
                        caption=caption,
                        parse_mode="Markdown",
                        reply_markup=get_quantity_keyboard(category_key, sub_key, product_key)
                    )
                    sent_photo = True
                except Exception as e2:
                    logger.error(f"Failed to send placeholder image '{placeholder}': {e2}. Falling back to text only.")
            if not sent_photo:
                await query.message.reply_text(
                    text=f"{caption}\n\n🖼️ Image preview unavailable.",
                    parse_mode="Markdown",
                    reply_markup=get_quantity_keyboard(category_key, sub_key, product_key)
                )
            try:
                await query.edit_message_text("Select a quantity from the product card above.")
            except Exception:
                pass

        elif data.startswith("quantity|"):
            _, category_key, sub_key, product_key, qty = data.split("|")
            cart = context.bot_data.setdefault("cart", {}).setdefault(user_key, [])
            cart.append({
                "category": category_key,
                "subcategory": sub_key,
                "product": product_key,
                "quantity": qty
            })
            _log_user_action(update, context, 'add_to_cart', {'product_key': product_key, 'qty': qty})
            await query.edit_message_text(
                text=f"✅ Added *{qty}* of *{product_key.replace('_', ' ').title()}* to your cart!",
                parse_mode="Markdown",
                reply_markup=main_menu(user_key, context.bot_data)
            )

        elif data.startswith("custom_qty|"):
            _, category_key, sub_key, product_key = data.split("|")
            context.user_data["awaiting_custom_qty"] = {
                "category": category_key,
                "subcategory": sub_key,
                "product": product_key
            }
            await query.edit_message_text("✏️ Please type the quantity you want (e.g. 10, 2, etc.)")

        elif data == "cart":
            cart_items = context.bot_data.get("cart", {}).get(user_key, [])
            logger.info(f"Cart items for user {user_key}: {cart_items}")
            _log_user_action(update, context, 'view_cart')
            if cart_items:
                text_items, total = _cart_summary_and_total(context.bot_data, user_key)
                text = "🛒 Your Cart:\n" + "\n".join(text_items) + f"\n\n*Total:* {total:.2f}€"
                checkout_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🧾 Checkout", callback_data="checkout")],
                    [InlineKeyboardButton("⬅️ Back to Menu", callback_data="main_menu")]
                ])
                await query.edit_message_text(text, parse_mode="Markdown", reply_markup=checkout_kb)
            else:
                text = "🛒 Your cart is currently empty."
                await query.edit_message_text(text, reply_markup=main_menu(user_key, context.bot_data))

        elif data == "checkout":
            text_items, total = _cart_summary_and_total(context.bot_data, user_key)
            _log_user_action(update, context, 'start_checkout')
            context.user_data['checkout'] = {
                'name': None,
                'address': None,
                'note': None,
            }
            context.user_data['checkout_state'] = 'awaiting_name'
            summary = "🧾 Checkout Summary:\n" + "\n".join(text_items) + f"\n\n*Total:* {total:.2f}€\n\n"
            summary += "Please enter your Full Name:"
            await query.edit_message_text(summary, parse_mode="Markdown")

        elif data == "pay_btc":
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("I have paid (Confirm)", callback_data="confirm_payment|btc")],
                [InlineKeyboardButton("⬅️ Back to Cart", callback_data="cart")]
            ])
            _log_user_action(update, context, 'choose_payment', {'method': 'btc'})
            btc = DATA.get('bot', {}).get('payment', {}).get('btc', 'N/A')
            await query.edit_message_text(
                f"🪙 Send BTC to:\n`{btc}`\n\nAfter sending, click *I have paid* to confirm.",
                parse_mode="Markdown",
                reply_markup=kb
            )

        elif data == "pay_usdt":
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("I have paid (Confirm)", callback_data="confirm_payment|usdt")],
                [InlineKeyboardButton("⬅️ Back to Cart", callback_data="cart")]
            ])
            _log_user_action(update, context, 'choose_payment', {'method': 'usdt'})
            usdt = DATA.get('bot', {}).get('payment', {}).get('usdt_trc20', 'N/A')
            await query.edit_message_text(
                f"🪙 Send USDT to:\n`TRC20 {usdt}`\n\nAfter sending, click *I have paid* to confirm.",
                parse_mode="Markdown",
                reply_markup=kb
            )

        elif data.startswith("confirm_payment|"):
            try:
                _, method = data.split("|", 1)
            except ValueError:
                method = 'unknown'
            text_items, total = _cart_summary_and_total(context.bot_data, user_key)
            order_summary = "\n".join(text_items)
            details = context.user_data.get('checkout', {})
            name = details.get('name') or '-'
            address = details.get('address') or '-'
            note = details.get('note') or '-'
            order_text = (
                f"Order via {method.upper()}:\n{order_summary}\n\n"
                f"Total: {total:.2f}€\n\n"
                f"Shipping Details:\n"
                f"• Name: {name}\n"
                f"• Address: {address}\n"
                f"• Note: {note}"
            )
            orders = context.bot_data.setdefault('orders', {}).setdefault(user_key, [])
            orders.append(order_text)
            context.bot_data.setdefault('cart', {})[user_key] = []
            context.user_data.pop('checkout_state', None)
            context.user_data.pop('checkout', None)
            _log_user_action(update, context, 'confirm_payment', {'method': method, 'total': total})
            await query.edit_message_text(
                f"✅ Payment confirmed and order placed.\n\n{order_text}",
                reply_markup=main_menu(user_key, context.bot_data)
            )

        elif data == "orders":
            orders = context.bot_data.get("orders", {}).get(user_key, [])
            if orders:
                text = "📦 Your Orders:\n" + "\n".join(orders)
            else:
                text = "📦 You have no orders yet."
            await query.edit_message_text(text, reply_markup=main_menu(user_key, context.bot_data))

        else:
            logger.warning(f"Unhandled callback data: {data}")
            await query.edit_message_text(
                "⚠️ Unknown action. Returning to main menu.",
                reply_markup=main_menu(user_key, context.bot_data)
            )

    except BadRequest as e:
        logger.error(f"BadRequest in callback_handler: {e}", exc_info=True)
        if "Query is too old" in str(e) or "message is not modified" in str(e):
            return
        try:
            await query.edit_message_text(
                "🤖 A request error occurred. Please try again.",
                reply_markup=main_menu(user_key, context.bot_data)
            )
        except Exception:
            logger.exception("Failed to send BadRequest message to user")
    except Exception as e:
        logger.error(f"General Exception in callback_handler: {e}", exc_info=True)
        try:
            await query.edit_message_text("🤖 Oops! Something went wrong. Please try again.", reply_markup=main_menu(user_key, context.bot_data))
        except Exception as e_inner:
            logger.error(f"Failed to send error message to user: {e_inner}", exc_info=True)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Use /reviews to see product reviews or use the menu buttons.")


async def handle_custom_quantity_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_key, user_id, username = _get_user_identity(update)
    text = update.message.text.strip()
    logger.info(f"Text input from user {user_id}: {text}")

    # 1) Checkout info collection state machine
    checkout_state = context.user_data.get('checkout_state')
    if checkout_state:
        details = context.user_data.setdefault('checkout', {})
        if checkout_state == 'awaiting_name':
            details['name'] = text
            context.user_data['checkout_state'] = 'awaiting_address'
            await update.message.reply_text("📍 Enter your Delivery Address (street, city, postcode, country):")
            return
        elif checkout_state == 'awaiting_address':
            details['address'] = text
            context.user_data['checkout_state'] = 'awaiting_note'
            await update.message.reply_text("📝 Enter a Delivery Note (optional). Type 'None' to skip:")
            return
        elif checkout_state == 'awaiting_note':
            details['note'] = None if text.lower() in ['none', 'no', 'skip'] else text
            text_items, total = _cart_summary_and_total(context.bot_data, user_key)
            summary = "🧾 Checkout Summary:\n" + "\n".join(text_items) + f"\n\n*Total:* {total:.2f}€\n\n"
            summary += (
                "Shipping Details:\n"
                f"• Name: {details.get('name','-')}\n"
                f"• Address: {details.get('address','-')}\n"
                f"• Note: {details.get('note') or '-'}\n\n"
                "Choose a payment method:"
            )
            context.user_data['checkout_state'] = 'ready_for_payment'
            await update.message.reply_text(summary, parse_mode="Markdown", reply_markup=get_payment_keyboard())
            return

    # 2) Custom quantity input flow
    custom_input_key = "awaiting_custom_qty"
    if custom_input_key not in context.user_data:
        logger.warning(f"No known input state for user {user_key}. Ignoring text input.")
        return

    if not text.isdigit():
        await update.message.reply_text("❌ Please enter a valid number.")
        return

    custom_qty = text
    details = context.user_data[custom_input_key]
    cat_key = details["category"]
    sub_key = details["subcategory"]
    prod_key = details["product"]

    product = DATA['categories'][cat_key]["subcategories"][sub_key]["products"][prod_key]

    if isinstance(product.get("quantities"), dict):
        unit_price_str = product["quantities"].get("1", product.get("price", "50€"))
        unit_price_str = str(unit_price_str).split("€")[0]
        try:
            unit_price = float(unit_price_str.replace("€", "").replace("/unit", "").strip())
        except ValueError:
            logger.error(f"Could not parse unit price from string: {unit_price_str}. Defaulting to 50.")
            unit_price = 50.0
    else:
        unit_price_str = str(product.get("price", "50€")).split("€")[0]
        try:
            unit_price = float(unit_price_str.replace("€", "").replace("/unit", "").strip())
        except ValueError:
            logger.error(f"Could not parse product price: {product.get('price')}. Defaulting to 50.")
            unit_price = 50.0

    total_price = int(custom_qty) * unit_price

    cart_item = {
        "product": product["name"],
        "qty": custom_qty,
        "price": f"{total_price:.2f}€"
    }
    context.bot_data.setdefault("cart", {}).setdefault(user_key, []).append(cart_item)
    logger.info(f"Added to cart for user {user_key}: {cart_item}")
    _log_user_action(update, context, 'add_to_cart', {'product': product['name'], 'qty': custom_qty, 'price': f"{total_price:.2f}€"})

    context.user_data.pop(custom_input_key)

    await update.message.reply_text(
        f"✅ *{custom_qty}* of *{product['name']}* added to cart!\n\nYou can continue shopping or view your cart.",
        parse_mode="Markdown",
        reply_markup=main_menu(user_key, context.bot_data)
    )


def main():
    # Load JSON data first
    load_data()

    HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")
    PORT = int(os.environ.get("PORT", 10000))
    WEBHOOK_PATH = "/webhook"

    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN not set.")
        raise Exception("❌ BOT_TOKEN not set.")
    if not HOSTNAME and WEBHOOK_PATH != "/webhook_local_test":
        logger.info("Running in polling mode since RENDER_EXTERNAL_HOSTNAME not set.")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reviews", reviews_command))
    app.add_handler(CommandHandler("faqs", faqs_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_quantity_input))

    if HOSTNAME:
        logger.info(f"✅ Starting webhook server on port {PORT}...")
        logger.info(f"🔗 Webhook URL: https://{HOSTNAME}{WEBHOOK_PATH}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH,
            webhook_url=f"https://{HOSTNAME}{WEBHOOK_PATH}"
        )
    else:
        logger.info("✅ Starting bot in polling mode...")
        app.run_polling()


if __name__ == "__main__":
    main()
