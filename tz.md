# Telegram Price Monitoring + Stories Automation

## Translated and cleaned project brief

## 1. Sources

- Connect 2-3 Telegram channels that publish prices.
- Collect the latest messages from each day.
- Extract products and prices.
- Ignore irrelevant items.
- Work even when message formats differ.

## 2. Required products

- iPhone Pro 256 GB
- iPhone Pro 512 GB
- iPhone Pro 1 TB
- iPhone Pro Max 256 GB
- iPhone Pro Max 512 GB
- iPhone Pro Max 1 TB
- iPhone Air
- MacBook Neo
- AirPods Pro 3
- Whoop 5.0 Peak
- PS5
- Apple Watch S11

## 3. Name normalization

Different product names should be normalized to one standard format.

Examples: iPhone 17 Pro 256 / 17 Pro 256 GB / Pro 256 / айфон про 256.

Final normalized name: iPhone Pro 256 GB.

## 4. Pricing logic

- Find the competitor price.
- Choose the lowest available price.
- My price = competitor price - 500 RUB.
- If no price is found, keep the old price from my price list.
- If the price changes by more than 3,000 RUB, highlight it in the report.

## 5. My base price list

The script should take my price-list template and update only the prices.

Any tech in stock at a great price 🔥

### iPhone

- Pro 256 GB — XXX RUB
- Pro 512 GB — XXX RUB
- Pro 1 TB — XXX RUB
- Pro Max 256 GB — XXX RUB
- Pro Max 512 GB — XXX RUB
- Pro Max 1 TB — XXX RUB
- Air — XXX RUB
- eSIM price

### Other products

- MacBook Neo — XXX RUB
- AirPods Pro 3 — XXX RUB
- Whoop 5.0 Peak — XXX RUB
- PS5 — XXX RUB
- Apple Watch S11 — XXX RUB

All items are original, but stock is limited!

Delivery in Moscow within 2 hours

To order, message me: @svyat_001

## 6. Story generation

There is a `backgrounds/` folder with ready-made background images:
https://drive.google.com/drive/folders/1P0Ajk13ltRw8HmT-6bjqeWaR89v9vZ15

- Take 3 images from the folder.
- Crop or adapt them to 1080 × 1920.
- Apply a light blur.
- Darken or brighten the background for readability.
- Add a semi-transparent panel behind the text.
- Overlay the price list in a clean style.
- Save 3 finished story images.

### Story style requirements

- Premium, minimal, and easy to read on a phone.
- Large prices, proper spacing, and good line height.
- No clutter.
- It should not look like a cheap ad banner.

If the text is hard to read, goes out of bounds, or looks cheap or overloaded, the test is considered failed.

## 7. Telegram delivery

Send me in Telegram: the updated price text, 3 finished story images, and a short report with the found prices.

Auto-posting stories: for the test, it is acceptable to demonstrate this on your own Telegram account.

If auto-posting is impossible or risky, explain why honestly.

Also describe the userbot option separately: Telethon / Pyrogram.

Do not store sessions or tokens in GitHub.

## 8. Automation

- Set up a daily run using cron / systemd timer / Docker schedule / another normal approach.
- The run time is defined in the config.
- Errors must be logged.
- If prices are not found, send a notification.
- If a channel is unavailable, send a notification.

## 9. Config

- List of Telegram channels.
- List of required products.
- Base price list.
- Pricing rule: minus 500 RUB from the competitor.
- Blur strength.
- Overlay transparency.
- Font size.
- Padding / margins.
- Telegram ID for sending the result.
- Daily run time.

## 10. Technologies

- Python or Node.js.
- Telethon / Pyrogram.
- Pillow / ImageMagick / HTML-to-image.
- Docker / Docker Compose.
- SQLite / JSON / CSV for storing price history.

The main goal is stability and a setup that is easy to run and maintain.

## 11. What to deliver

- GitHub / GitLab repository link.
- Run instructions.
- `.env.example`.
- `config.example`.
- 3 finished story images.
- Updated price text.
- Short report on the found prices.
- 3-5 minute demo video.
- Architecture description.
- List of risks and limitations.

## Recommended stack: best value for money

If the goal is the lowest cost with good stability, I recommend this stack:

- Backend: Python 3.11+
- Telegram access: Telethon, with Pyrogram as an alternative
- Parsing and matching: regex + Pydantic + optional simple NLP/LLM fallback only for ambiguous cases
- Story images: Pillow for the main implementation; HTML-to-image only if you want more design flexibility
- Storage: SQLite
- Scheduling: cron or systemd timer inside Docker
- Deployment: Docker Compose
- Logging: standard Python logging + rotating log files
- Config: `.env` for secrets and `config.yaml` / `config.json` for business settings

### Why this stack

- Python is the cheapest and fastest option to build and maintain for this use case.
- Telethon is a strong fit because it works directly with Telegram's API layer and is well suited to user-account automation.
- SQLite is enough for a small MVP and avoids the cost and maintenance of a separate database server.
- Pillow keeps image generation simple and lightweight.
- Docker Compose makes the deployment repeatable without adding unnecessary infrastructure.

### Suggested architecture

1. Fetch messages from selected channels.
2. Normalize product names and extract prices.
3. Compare competitor prices and calculate the new price list.
4. Render the updated price text.
5. Generate 3 story images from background templates.
6. Save price history and a report.
7. Send everything to Telegram and log the run.

### Practical note

Telegram’s Bot API is for bots, while stories are exposed in Telegram’s broader API layer. For the cheapest reliable implementation of channel reading and story-related automation, a userbot approach with Telethon or Pyrogram is usually the practical choice; the Bot API can still be used for notifications and simple bot interactions.

This is a recommendation, not a guarantee of every edge case.
