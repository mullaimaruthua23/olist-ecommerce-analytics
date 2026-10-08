-- ============================================================
-- OLIST E-COMMERCE ANALYTICS
-- ============================================================


-- 1. Overall order and revenue KPIs
SELECT
    COUNT(DISTINCT order_id) AS total_orders,
    ROUND(SUM(revenue), 2) AS total_revenue,
    ROUND(SUM(revenue) / COUNT(DISTINCT order_id), 2) AS average_order_value
FROM fact_orders;


-- 2. Revenue by month
SELECT
    order_month,
    ROUND(SUM(revenue), 2) AS monthly_revenue
FROM fact_orders
GROUP BY order_month
ORDER BY order_month;


-- 3. Month-over-month revenue growth using LAG
WITH monthly_sales AS (
    SELECT
        order_month,
        SUM(revenue) AS monthly_revenue
    FROM fact_orders
    GROUP BY order_month
)
SELECT
    order_month,
    ROUND(monthly_revenue, 2) AS monthly_revenue,
    ROUND(
        (
            monthly_revenue
            - LAG(monthly_revenue) OVER (ORDER BY order_month)
        )
        / LAG(monthly_revenue) OVER (ORDER BY order_month)
        * 100,
        2
    ) AS mom_growth_pct
FROM monthly_sales
ORDER BY order_month;


-- 4. Top 10 product categories by revenue
SELECT
    category,
    ROUND(SUM(price), 2) AS total_revenue
FROM fact_items
GROUP BY category
ORDER BY total_revenue DESC
LIMIT 10;


-- 5. Late delivery percentage by state
SELECT
    customer_state,
    COUNT(*) AS total_orders,
    SUM(is_late) AS late_orders,
    ROUND(AVG(is_late) * 100, 2) AS late_delivery_pct
FROM fact_orders
GROUP BY customer_state
ORDER BY late_delivery_pct DESC;


-- 6. Average review score: late vs on-time delivery
SELECT
    CASE
        WHEN is_late = 1 THEN 'Late'
        ELSE 'On-Time'
    END AS delivery_status,
    COUNT(*) AS total_orders,
    ROUND(AVG(review_score), 2) AS average_review_score
FROM fact_orders
WHERE review_score IS NOT NULL
GROUP BY is_late
ORDER BY is_late;


-- 7. Top 5 products per category by revenue
WITH product_revenue AS (
    SELECT
        category,
        product_id,
        ROUND(SUM(price), 2) AS total_revenue
    FROM fact_items
    GROUP BY category, product_id
),
ranked_products AS (
    SELECT
        category,
        product_id,
        total_revenue,
        RANK() OVER (
            PARTITION BY category
            ORDER BY total_revenue DESC
        ) AS product_rank
    FROM product_revenue
)
SELECT
    category,
    product_id,
    total_revenue,
    product_rank
FROM ranked_products
WHERE product_rank <= 5
ORDER BY category, product_rank;


-- 8. Revenue by RFM customer segment
SELECT
    segment,
    COUNT(*) AS customers,
    ROUND(SUM(monetary), 2) AS total_revenue,
    ROUND(AVG(monetary), 2) AS average_customer_revenue
FROM rfm
GROUP BY segment
ORDER BY total_revenue DESC;