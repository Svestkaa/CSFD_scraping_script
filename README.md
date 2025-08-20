# 🎬 CSFD Web Scraper (Python + Selenium)

This repository contains a **web scraping script** for extracting movie ratings and reviews from [ČSFD](https://www.csfd.cz/).  
It is designed to handle **dynamic content, retries, automated restarts, and progress tracking**.  

> Based on the original CSFD script by [Dino6Ao](https://github.com/Dino6Ao).

---

## ✨ Features

- **Selenium Integration** – Works with dynamically rendered JS content.  
- **Automated Restarts** – Handles crashes and session invalidation.  
- **Progress Tracking** – Skips already scraped data, resumes where it left off.  
- **Headless Mode** – Run without browser window (server-friendly).  
- **Configurable Delays** – Avoids IP bans and server overload.  
- **Extensible** – Can be easily modified for other scraping tasks.  

---

## 🚀 Usage

### 1. Get User ID  
Find the user ID in profile URL:  
Example: [https://www.csfd.cz/uzivatel/95-golfista/prehled/](https://www.csfd.cz/uzivatel/95-golfista/prehled/)  
→ User ID = **95**

Run the script with:  
```bash
python csfd.py --user 95 --ratings
python csfd.py --user 95 --reviews


## 🔑 Get Permanent Login Token

1. Log in to **ČSFD** in your browser.  
2. Open **DevTools** → **Application** → **Cookies**.  
3. Copy your `permanent_login_token` into a file named **`csfd_cookie.txt`**.  
4. [Microsoft Edge/Chrome cookie guide](https://learn.microsoft.com/en-us/microsoft-edge/devtools-guide-chromium/storage/cookies).  

---

## 📦 Requirements

- [Python 3.x](https://www.python.org/downloads/)  
- [Selenium](https://pypi.org/project/selenium/) → `pip install selenium`  
- [Google Chrome](https://www.google.com/chrome/)  
- [ChromeDriver](https://chromedriver.chromium.org/downloads) (same version as Chrome)  

> Make sure `chromedriver` is in the same directory or in your system **PATH**.

---

## ⚙️ How It Works

1. Loads cookies (`csfd_cookie.txt`).  
2. Starts Selenium (headless if configured).  
3. Reads user ID and parameters (`--ratings` / `--reviews`).  
4. Checks existing CSV → skips already scraped entries.  
5. Goes through all pages of ratings/reviews.  
6. Extracts movie details (title, year, directors, actors, ratings, review).  
7. Handles errors (e.g., `InvalidSessionIdException`) → auto-restarts.  
8. Saves results into CSV.  

---

## 📊 Outputs

### `csfd_ratings.csv`
- `csfd_id`, `title`, `year`, `countries`  
- `directors`, `actor1`, `actor2`  
- `overall_rating` (average from CSFD)  
- `date`, `rating` (converted to %)  

### `csfd_reviews.csv`
- Same as ratings +  
- `review` – full review text (semicolon `;` replaced with comma).  

---

## 🌍 Language Settings

By default, titles are exported in **Czech**.  

To change language:  
1. Go to **Profile → Settings → View → Movie title priority**.  
2. Choose your preferred language (e.g., English).  
3. Update `csfd_cookie.txt` with the new token.  
4. Run the script again.  
