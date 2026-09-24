# ⚡ Enterprise Amazon Scraper API

> **A high-speed, anti-bot resilient Amazon product intelligence microservice built with FastAPI & Python.**

[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Docker Ready](https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)](#)
[![RapidAPI](https://img.shields.io/badge/RapidAPI-Monetized-0052CC?style=for-the-badge&logo=rapidapi&logoColor=white)](#)

---

## 🚀 Overview

**Amazon Scraper API** is an asynchronous microservice engineered to extract clean, structured product data from multiple Amazon marketplaces in under a second. Built on top of **FastAPI**, **curl_cffi**, and **Selectolax**, it bypasses standard WAF/Anti-Bot protections by mimicking real browser TLS fingerprints and HTTP/2 requests.

Designed for seamless deployment on **Render** and instant listing on **RapidAPI Marketplace**.

---

## ✨ Key Features

* 🛡️ **Anti-Bot Shield Bypass:** Utilizes `curl_cffi` for browser-level HTTP/2 and TLS signature impersonation (`chrome120`).
* ⚡ **Lightning Fast Parsing:** Powered by `Selectolax` (C-based HTML parser) for ultra-low response latencies ($<10\text{ ms}$ cached).
* 📦 **Comprehensive Product Intelligence:** Extracts titles, prices, ratings, availability, sellers, high-res images, categories, bullet points, and clean technical spec tables.
* ⚡ **Built-In TTL Caching:** Integrated `cachetools` layer prevents redundant requests, lowers bandwidth usage, and stops IP bans.
* 🔒 **RapidAPI Proxy Security:** Validates `X-RapidAPI-Proxy-Secret` headers to prevent unauthorized direct backend access.
* 📝 **Enterprise Error Tracing:** Includes unique `request_id` tracking on all 4xx/5xx responses for easy debugging.

---

## 🛠️ Tech Stack

* **Framework:** FastAPI / Uvicorn
* **Scraping Engine:** `curl_cffi` (TLS Fingerprinting) + `Selectolax`
* **Validation:** Pydantic v2
* **Caching:** `cachetools` (15-min TTL)
* **Containerization:** Docker

---

## 📊 Sample JSON Output

```json
{
  "asin": "B005GQW0OW",
  "title": "Premium Photo Paper, 68 lbs., Semi-Gloss, 13 x 19, 20 Sheets/Pack",
  "badge": "Amazon's Choice",
  "price": "PKR 3,838",
  "numeric_price": 3838.0,
  "original_price": "PKR 10,302.69",
  "discount_percentage": "63%",
  "currency": "PKR",
  "rating": "5.0 / 5",
  "ratings_count": 1,
  "availability": "Currently unavailable. We don't know when or if this item will be back in stock.",
  "seller_info": "Ships from and sold by Amazon.com",
  "image_url": "[https://m.media-amazon.com/images/I/61+7Q0nx7GL._AC_SL1500_.jpg](https://m.media-amazon.com/images/I/61+7Q0nx7GL._AC_SL1500_.jpg)",
  "category_path": [
    "Office Products",
    "Paper",
    "Photo Paper"
  ],
  "specifications": {
    "Item Weight": "68 pounds",
    "Paper Size": "13 x 19",
    "Brand Name": "Epson"
  },
  "bullet_points": [
    "High quality photo paper",
    "Semi-gloss finish"
  ],
  "product_url": "[https://www.amazon.com/dp/B005GQW0OW](https://www.amazon.com/dp/B005GQW0OW)"
}
