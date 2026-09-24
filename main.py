import asyncio
import re
import random
import logging
import uuid
import os
import json
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Query, Request, Header, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ValidationError
from selectolax.parser import HTMLParser
from fake_useragent import UserAgent
from curl_cffi.requests import AsyncSession
from cachetools import TTLCache

# Configure Enterprise Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rapidapi_amazon_scraper")

app = FastAPI(
    title="Enterprise Amazon Scraper API (RapidAPI Ready)",
    description="High-speed, anti-bot resilient Amazon product intelligence API.",
    version="2.1.0"
)

# In-memory TTL cache (Holds max 1000 items for 15 minutes)
RESPONSE_CACHE = TTLCache(maxsize=1000, ttl=900)

RAPIDAPI_PROXY_SECRET = os.getenv("RAPIDAPI_PROXY_SECRET", None)
ua = UserAgent(browsers=['chrome', 'edge'])


# ------------------------------------------------------------------------------
# 1. ENHANCED PYDANTIC SCHEMAS
# ------------------------------------------------------------------------------

class ValidationErrorDetail(BaseModel):
    loc: List[str] = Field(..., description="Location of validation error")
    msg: str = Field(..., description="Error message")
    type: str = Field(..., description="Error type")


class CustomHTTPValidationError(BaseModel):
    status: str = Field("error", examples=["error"])
    error_type: str = Field("ValidationException", examples=["ValidationException"])
    message: str = Field("Input parameters failed validation.", examples=["Validation error"])
    request_id: str = Field(..., examples=["req_12345678"])
    details: List[ValidationErrorDetail]


class ErrorResponse(BaseModel):
    status: str = Field("error", examples=["error"])
    error_type: str = Field(..., examples=["AntiBotException"])
    message: str = Field(..., examples=["Request failed during upstream fetch."])
    request_id: str = Field(..., examples=["req_12345678"])
    details: Optional[Any] = None


class ProductData(BaseModel):
    asin: str = Field(..., description="Amazon Standard Identification Number")
    title: Optional[str] = Field(None, description="Product Title")
    badge: Optional[str] = Field(None, description="Amazon Choice / Best Seller badge")
    price: Optional[str] = Field(None, description="Formatted current price")
    numeric_price: Optional[float] = Field(None, description="Current price as float")
    original_price: Optional[str] = Field(None, description="List price before discount")
    discount_percentage: Optional[str] = Field(None, description="Savings percentage")
    currency: Optional[str] = Field(None, description="Currency code or symbol")
    rating: Optional[str] = Field(None, description="User rating out of 5")
    ratings_count: Optional[int] = Field(None, description="Total review count")
    availability: Optional[str] = Field(None, description="Stock status")
    seller_info: Optional[str] = Field(None, description="Sold by and shipped by info")
    image_url: Optional[str] = Field(None, description="Primary high-res product image")
    images: List[str] = Field(default=[], description="Full gallery of high-res product images")
    category_path: List[str] = Field(default=[], description="Breadcrumb category hierarchy")
    specifications: Dict[str, str] = Field(default={}, description="Key-value technical details")
    bullet_points: List[str] = Field(default=[], description="Feature highlights")
    product_url: str = Field(..., description="Direct product URL")


# ------------------------------------------------------------------------------
# 2. CUSTOM EXCEPTION CLASSES
# ------------------------------------------------------------------------------

class AmazonScraperException(Exception):
    def __init__(self, message: str, status_code: int = 500, details: Optional[Any] = None):
        self.message = message
        self.status_code = status_code
        self.details = details


class AntiBotBlockedException(AmazonScraperException):
    def __init__(self, details: Optional[Any] = None):
        super().__init__(
            message="Amazon Anti-Bot challenge detected. Retry request or route via proxies.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            details=details
        )


class ProductNotFoundException(AmazonScraperException):
    def __init__(self, asin: str, domain: str):
        super().__init__(
            message=f"Product '{asin}' not found on amazon.{domain}.",
            status_code=status.HTTP_404_NOT_FOUND
        )


# ------------------------------------------------------------------------------
# 3. GLOBAL ERROR HANDLERS WITH REQUEST ID TRACING
# ------------------------------------------------------------------------------

@app.middleware("http")
async def add_request_id_middleware(request: Request, call_next):
    request.state.request_id = f"req_{uuid.uuid4().hex[:10]}"
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    req_id = getattr(request.state, "request_id", "unknown")
    formatted_errors = [
        {"loc": [str(i) for i in err.get("loc", [])], "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "status": "error",
            "error_type": "RequestValidationError",
            "message": "Input parameter validation failed.",
            "request_id": req_id,
            "details": formatted_errors
        }
    )


@app.exception_handler(AmazonScraperException)
async def custom_scraper_exception_handler(request: Request, exc: AmazonScraperException):
    req_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "error_type": exc.__class__.__name__,
            "message": exc.message,
            "request_id": req_id,
            "details": exc.details
        }
    )


@app.exception_handler(Exception)
async def global_catch_all_handler(request: Request, exc: Exception):
    req_id = getattr(request.state, "request_id", "unknown")
    logger.critical(f"[{req_id}] System crash: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": "error",
            "error_type": "InternalServerError",
            "message": "An unexpected error occurred. Reference the request_id when opening a support ticket.",
            "request_id": req_id,
            "details": None
        }
    )


# ------------------------------------------------------------------------------
# 4. CLEAN & REFINED PARSER (WITH MULTI-IMAGE GALLERY)
# ------------------------------------------------------------------------------

def clean_text(text: Optional[str]) -> Optional[str]:
    """Helper to remove non-breaking spaces and redundant whitespaces."""
    if not text:
        return None
    cleaned = text.replace('\xa0', ' ').replace('\u200b', '')
    return " ".join(cleaned.split())


def parse_amazon_html(html: str, asin: str, url: str) -> ProductData:
    tree = HTMLParser(html)
    
    # Strip script, style, noscript, svg
    for tag in tree.css("script, style, noscript, svg"):
        tag.decompose()
        
    # Title
    title_node = tree.css_first("#productTitle") or tree.css_first("h1#title")
    title = clean_text(title_node.text()) if title_node else None

    # Badge
    badge_node = tree.css_first("span.a-badge-text") or tree.css_first(".ac-badge-wrapper")
    badge = clean_text(badge_node.text()) if badge_node else None

    # Prices
    price_str = None
    original_price = None
    discount_pct = None
    numeric_price = None
    currency = "$"

    price_selectors = [
        "span.a-price span.a-offscreen",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        "#corePrice_feature_div span.a-offscreen",
        "#corePriceDisplay_desktop_feature_div span.a-offscreen"
    ]
    
    for selector in price_selectors:
        price_node = tree.css_first(selector)
        if price_node and price_node.text(strip=True):
            price_str = clean_text(price_node.text())
            break

    orig_price_node = tree.css_first("span.a-price.a-text-price span.a-offscreen")
    if orig_price_node:
        original_price = clean_text(orig_price_node.text())

    discount_node = tree.css_first("span.savingsPercentage")
    if discount_node:
        discount_pct = clean_text(discount_node.text())

    if price_str:
        match = re.search(r"([^\d\s,.]+)?\s*([\d,]+\.?\d*)", price_str)
        if match:
            currency = match.group(1) or "$"
            try:
                numeric_price = float(match.group(2).replace(",", ""))
            except ValueError:
                numeric_price = None

    # Rating
    rating = None
    rating_node = (
        tree.css_first("i.a-icon-star span.a-icon-alt") 
        or tree.css_first("#acrPopover")
        or tree.css_first("span[data-hook='rating-out-of-text']")
    )
    if rating_node:
        rating_text = clean_text(rating_node.text() or rating_node.attributes.get("title", ""))
        if rating_text:
            rating_match = re.search(r"(\d+(\.\d+)?)\s*out of 5", rating_text, re.IGNORECASE)
            if rating_match:
                val = float(rating_match.group(1))
                rating = f"{val:.1f} / 5"
            else:
                rating = rating_text

    # Ratings Count
    ratings_count = None
    review_node = tree.css_first("#acrCustomerReviewText") or tree.css_first("span[data-hook='total-review-count']")
    if review_node:
        count_match = re.search(r"([\d,]+)", review_node.text(strip=True))
        if count_match:
            try:
                ratings_count = int(count_match.group(1).replace(",", ""))
            except ValueError:
                ratings_count = None

    # Availability
    avail_node = tree.css_first("#availability")
    availability = clean_text(avail_node.text()) if avail_node else "Unknown"
    if availability:
        availability = re.sub(r'([a-z0-9\.])([A-Z])', r'\1 \2', availability)

    # Seller Info
    merchant_node = tree.css_first("#merchant-info") or tree.css_first("#sellerProfileTriggerId")
    seller_info = clean_text(merchant_node.text()) if merchant_node else None

    # --------------------------------------------------------------------------
    # HIGH-RES MULTI-IMAGE & GALLERY EXTRACTION
    # --------------------------------------------------------------------------
    image_url = None
    images = []

    img_node = tree.css_first("#landingImage") or tree.css_first("#imgBlkFront") or tree.css_first("#main-image")
    if img_node:
        # Extract primary image
        image_url = img_node.attributes.get("data-old-hires") or img_node.attributes.get("src")

        # Extract dynamic high-res gallery images JSON if available
        dynamic_imgs_raw = img_node.attributes.get("data-a-dynamic-image")
        if dynamic_imgs_raw:
            try:
                img_dict = json.loads(dynamic_imgs_raw)
                images = list(img_dict.keys())
            except Exception:
                pass

    # Fallback/Additional gallery images from thumbnail list
    if not images:
        alt_img_nodes = tree.css("#altImages img, #imageBlock img")
        for img in alt_img_nodes:
            src = img.attributes.get("src")
            if src and "media-amazon.com/images/I/" in src:
                # Convert thumbnail URL to high-res by stripping sizing modifiers
                high_res_src = re.sub(r"\._[A-Z0-9_]+_\.", ".", src)
                if high_res_src not in images and not high_res_src.endswith(".gif"):
                    images.append(high_res_src)

    if image_url and image_url not in images:
        images.insert(0, image_url)
    elif not image_url and images:
        image_url = images[0]

    # Categories
    category_path = []
    cat_container = tree.css_first("#wayfinding-breadcrumbs_feature_div")
    if cat_container:
        for a in cat_container.css("a.a-link-normal"):
            text = clean_text(a.text())
            if text:
                category_path.append(text)

    # Technical Specs
    specifications = {}
    spec_tables = tree.css("table.prodDetTable, #productDetails_techSpec_section_1, #detailBullets_feature_div")
    excluded_keys = ["customer reviews", "best sellers rank", "asin"]
    
    for table in spec_tables:
        for row in table.css("tr"):
            th = row.css_first("th")
            td = row.css_first("td")
            if th and td:
                k = clean_text(th.text())
                v = clean_text(td.text())
                if k and v and k.lower() not in excluded_keys:
                    specifications[k] = v

    # Bullet Points
    bullet_points = []
    bullets_container = tree.css_first("#feature-bullets")
    if bullets_container:
        for li in bullets_container.css("ul.a-unordered-list li"):
            text = clean_text(li.text())
            if text and not li.css_first(".a-expander-content"):
                bullet_points.append(text)

    return ProductData(
        asin=asin,
        title=title,
        badge=badge,
        price=price_str,
        numeric_price=numeric_price,
        original_price=original_price,
        discount_percentage=discount_pct,
        currency=currency,
        rating=rating,
        ratings_count=ratings_count,
        availability=availability,
        seller_info=seller_info,
        image_url=image_url,
        images=images,
        category_path=category_path,
        specifications=specifications,
        bullet_points=bullet_points,
        product_url=url,
    )


# ------------------------------------------------------------------------------
# 5. ENDPOINT CONTROLLER
# ------------------------------------------------------------------------------

@app.get(
    "/api/v1/scrape",
    response_model=ProductData,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"model": ErrorResponse, "description": "ASIN not found"},
        422: {"model": CustomHTTPValidationError, "description": "Validation Error"},
        429: {"model": ErrorResponse, "description": "Anti-bot triggered"},
        502: {"model": ErrorResponse, "description": "Upstream error"},
        503: {"model": ErrorResponse, "description": "Service unavailable"}
    }
)
async def scrape_amazon_product(
    request: Request,
    asin: str = Query(
        ..., 
        min_length=10, 
        max_length=10, 
        pattern=r"^[A-Z0-9]{10}$", 
        description="10-character Amazon ASIN"
    ),
    domain: str = Query(
        "com", 
        pattern=r"^(com|co\.uk|de|fr|co\.jp|ca|it|es|in)$", 
        description="Amazon store domain"
    ),
    x_rapidapi_proxy_secret: Optional[str] = Header(None, alias="X-RapidAPI-Proxy-Secret")
):
    if RAPIDAPI_PROXY_SECRET and x_rapidapi_proxy_secret != RAPIDAPI_PROXY_SECRET:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Direct API invocation unauthorized. Route requests through RapidAPI Gateway."
        )

    cache_key = f"{domain}:{asin}"
    if cache_key in RESPONSE_CACHE:
        logger.info(f"Serving ASIN {asin} from TTL Cache.")
        return RESPONSE_CACHE[cache_key]

    target_url = f"https://www.amazon.{domain}/dp/{asin}"
    
    async with AsyncSession(impersonate="chrome120") as session:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await asyncio.sleep(random.uniform(0.2, 0.6))
                
                response = await session.get(
                    target_url,
                    headers={"Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.google.com/"},
                    timeout=12.0
                )
                
                if response.status_code == 404:
                    raise ProductNotFoundException(asin=asin, domain=domain)

                if response.status_code in [503, 429, 405]:
                    await asyncio.sleep(1.5 ** attempt)
                    continue

                if "validateCaptcha" in response.text or "api-services-support@amazon.com" in response.text:
                    await asyncio.sleep(1.5 ** attempt)
                    continue

                data = parse_amazon_html(response.text, asin, target_url)
                RESPONSE_CACHE[cache_key] = data
                return data

            except ProductNotFoundException:
                raise
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for ASIN {asin}: {str(e)}")
                if attempt == max_retries - 1:
                    raise AntiBotBlockedException(details={"asin": asin, "domain": domain})

        raise AntiBotBlockedException(details={"asin": asin, "domain": domain})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
