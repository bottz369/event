"""BOTTZ AI — LINE Bot パッケージ(event-app モノリス Bot)。

§40 の B4「アー写更新」縦スライス。FastAPI Webhook を bot/main.py に実装し、
既存 services(artist_service)を直 import して再利用する。DB/画像ロジックは
既存 service に委譲し、この層は「Webhook 受信・署名検証・ガード・名前抽出・
画像 DL・通知」のみを持つ薄い層に留める。
"""
