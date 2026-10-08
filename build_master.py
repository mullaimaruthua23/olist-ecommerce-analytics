from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
from sqlalchemy import create_engine

import os
from dotenv import load_dotenv
load_dotenv()
# ============================================================
# PATHS
# ============================================================

RAW = Path("data/raw")
OUT = Path("data/processed")

OUT.mkdir(parents=True, exist_ok=True)


# ============================================================
# MYSQL CONNECTION
# ============================================================

PASSWORD = quote_plus(os.getenv("MYSQL_PASSWORD"))

engine = create_engine(
    f"mysql+pymysql://root:{PASSWORD}@localhost:3306/olist"
)


# ============================================================
# HELPER FUNCTION
# ============================================================

def read(name):
    return pd.read_csv(RAW / name)


# ============================================================
# 1. LOAD DATA
# ============================================================

orders = read("olist_orders_dataset.csv")
customers = read("olist_customers_dataset.csv")
items = read("olist_order_items_dataset.csv")
products = read("olist_products_dataset.csv")
payments = read("olist_order_payments_dataset.csv")
reviews = read("olist_order_reviews_dataset.csv")
translation = read("product_category_name_translation.csv")


# ============================================================
# 2. CLEAN ORDERS
# ============================================================

date_cols = [
    "order_purchase_timestamp",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
]

for c in date_cols:
    orders[c] = pd.to_datetime(orders[c], errors="coerce")

orders = orders.drop_duplicates("order_id")

# Keep only delivered orders
orders = orders[orders["order_status"] == "delivered"].copy()

# Remove orders without delivery date
orders = orders.dropna(subset=["order_delivered_customer_date"])

# Month of purchase
orders["order_month"] = (
    orders["order_purchase_timestamp"]
    .dt.to_period("M")
    .astype(str)
)

# Actual delivery days
orders["delivery_days"] = (
    orders["order_delivered_customer_date"]
    - orders["order_purchase_timestamp"]
).dt.days

# Delivery delay compared with estimated date
orders["delay_days"] = (
    orders["order_delivered_customer_date"]
    - orders["order_estimated_delivery_date"]
).dt.days

# 1 = late, 0 = on time
orders["is_late"] = (orders["delay_days"] > 0).astype(int)


# ============================================================
# 3. ORDER-LEVEL MONEY AND REVIEWS
# ============================================================

item_totals = items.groupby("order_id").agg(
    revenue=("price", "sum"),
    freight=("freight_value", "sum"),
    n_items=("order_item_id", "count"),
)

pay_totals = payments.groupby("order_id").agg(
    payment_value=("payment_value", "sum"),
    payment_type=("payment_type", "first"),
)

review_scores = reviews.groupby("order_id").agg(
    review_score=("review_score", "mean")
)


# ============================================================
# CREATE FACT ORDERS
# ============================================================

fact_orders = (
    orders.merge(
        customers[
            [
                "customer_id",
                "customer_unique_id",
                "customer_city",
                "customer_state",
            ]
        ],
        on="customer_id",
        how="left",
    )
    .merge(item_totals, on="order_id", how="left")
    .merge(pay_totals, on="order_id", how="left")
    .merge(review_scores, on="order_id", how="left")
)


fact_orders = fact_orders[
    [
        "order_id",
        "customer_unique_id",
        "customer_city",
        "customer_state",
        "order_purchase_timestamp",
        "order_month",
        "delivery_days",
        "delay_days",
        "is_late",
        "revenue",
        "freight",
        "n_items",
        "payment_value",
        "payment_type",
        "review_score",
    ]
].dropna(subset=["revenue"])


# ============================================================
# 4. ITEM-LEVEL TABLE WITH ENGLISH CATEGORY
# ============================================================

products = products.merge(
    translation,
    on="product_category_name",
    how="left",
)

products["category"] = (
    products["product_category_name_english"]
    .fillna("unknown")
)

fact_items = (
    items.merge(
        products[["product_id", "category"]],
        on="product_id",
        how="left",
    )
    .merge(
        fact_orders[
            [
                "order_id",
                "order_month",
                "customer_state",
            ]
        ],
        on="order_id",
        how="inner",
    )
)


# ============================================================
# 5. RFM ANALYSIS
# ============================================================

snapshot = (
    fact_orders["order_purchase_timestamp"].max()
    + pd.Timedelta(days=1)
)

rfm = fact_orders.groupby("customer_unique_id").agg(
    recency=(
        "order_purchase_timestamp",
        lambda s: (snapshot - s.max()).days,
    ),
    frequency=("order_id", "nunique"),
    monetary=("revenue", "sum"),
).reset_index()


# Rank first so ties do not break qcut
rfm["r_score"] = pd.qcut(
    rfm["recency"].rank(method="first"),
    5,
    labels=[5, 4, 3, 2, 1],
).astype(int)

rfm["f_score"] = pd.qcut(
    rfm["frequency"].rank(method="first"),
    5,
    labels=[1, 2, 3, 4, 5],
).astype(int)

rfm["m_score"] = pd.qcut(
    rfm["monetary"].rank(method="first"),
    5,
    labels=[1, 2, 3, 4, 5],
).astype(int)


def segment(row):
    if row["r_score"] >= 4 and row["m_score"] >= 4:
        return "Champions"

    if row["r_score"] >= 3 and row["m_score"] >= 3:
        return "Loyal"

    if row["r_score"] >= 4:
        return "New / Recent"

    if row["r_score"] <= 2 and row["m_score"] >= 4:
        return "At Risk (High Value)"

    if row["r_score"] <= 2:
        return "Inactive"

    return "Needs Attention"


rfm["segment"] = rfm.apply(segment, axis=1)


# ============================================================
# 6. SAVE PROCESSED CSV FILES
# ============================================================

fact_orders.to_csv(
    OUT / "fact_orders.csv",
    index=False,
)

fact_items.to_csv(
    OUT / "fact_items.csv",
    index=False,
)

rfm.to_csv(
    OUT / "rfm.csv",
    index=False,
)


# ============================================================
# 7. WRITE TABLES TO MYSQL
# ============================================================

fact_orders.to_sql(
    "fact_orders",
    engine,
    if_exists="replace",
    index=False,
    chunksize=5000,
)

fact_items.to_sql(
    "fact_items",
    engine,
    if_exists="replace",
    index=False,
    chunksize=5000,
)

rfm.to_sql(
    "rfm",
    engine,
    if_exists="replace",
    index=False,
    chunksize=5000,
)


# ============================================================
# 8. PRINT SANITY CHECK NUMBERS
# ============================================================

print("Orders:", len(fact_orders))
print(
    "Customers:",
    fact_orders["customer_unique_id"].nunique(),
)
print(
    "Total revenue:",
    round(fact_orders["revenue"].sum(), 2),
)
print(
    "Late delivery %:",
    round(
        fact_orders["is_late"].mean() * 100,
        2,
    ),
)
print(
    "Avg review:",
    round(
        fact_orders["review_score"].mean(),
        2,
    ),
)
print(
    "Repeat customers %:",
    round(
        (rfm["frequency"] > 1).mean() * 100,
        2,
    ),
)

print("\nRFM Segments:")
print(rfm["segment"].value_counts())

print("\nDone. Files saved in:", OUT)