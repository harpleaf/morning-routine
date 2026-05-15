name: 🌤️ 毎朝の天気をNotionに投稿

on:
  schedule:
    # 毎朝 6:30 JST = 21:30 UTC (前日)
    - cron: "30 21 * * *"
  workflow_dispatch:
    # 手動実行も可能

jobs:
  post-weather:
    runs-on: ubuntu-latest
    timeout-minutes: 5

    steps:
      - name: リポジトリをチェックアウト
        uses: actions/checkout@v4

      - name: Python セットアップ
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: 天気取得 → Notion投稿
        env:
          NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}
          NOTION_PAGE_ID: ${{ secrets.NOTION_PAGE_ID }}
        run: python morning_weather.py
