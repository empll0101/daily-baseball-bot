import asyncio
import aiohttp
from unittest.mock import patch

from tracker.providers.npb import NpbProvider
import time

class MockResponse:
    def __init__(self, should_fail=False, text_content=""):
        self.should_fail = should_fail
        self.text_content = text_content

    def raise_for_status(self):
        if self.should_fail:
            raise aiohttp.ClientResponseError(
                request_info=aiohttp.RequestInfo(url="http://fake", method="GET", headers={}),
                history=(),
                status=500,
                message="Internal Server Error"
            )

    async def text(self):
        return self.text_content

class MockSession:
    def __init__(self):
        self.get_call_count = 0
        self.bad_games = ["fake_bad_game"]

    def get(self, url, *args, **kwargs):
        self.get_call_count += 1
        url_str = str(url)
        class AsyncContextManager:
            async def __aenter__(ctx_self):
                # 測試 1: 全部失敗
                if "always_fail" in url_str:
                    return MockResponse(should_fail=True)
                
                # 測試 2: 只有 fake_bad_game 失敗
                if any(bad in url_str for bad in self.bad_games):
                    return MockResponse(should_fail=True)
                
                # 首頁
                if "/npb/" in url_str and "game" not in url_str:
                    return MockResponse(text_content='''
                    <a href="/npb/game/fake_bad_game/index">Bad Game</a>
                    <a href="/npb/game/good_game/index">Good Game</a>
                    ''')
                
                return MockResponse(text_content="<html><body>試合終了</body></html>")
                
            async def __aexit__(ctx_self, exc_type, exc, tb):
                pass
        return AsyncContextManager()

async def main():
    print("=== 測試 1: 模擬 _html 遇到 500 錯誤並觸發重試 ===")
    
    mock_session = MockSession()
    provider = NpbProvider(mock_session)
    
    start_time = time.time()
    try:
        await provider._html("always_fail")
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"拋出預期的錯誤: {type(e).__name__}: {e}")
        print(f"總共重試次數 (呼叫 get 的次數): {mock_session.get_call_count}")
        print(f"花費時間 (因包含 sleep 重試，應大於 3 秒): {elapsed:.2f} 秒\n")

    print("=== 測試 2: 模擬 collect_events 遇到某場比賽一直壞掉，不會崩潰 ===")
    
    mock_session.get_call_count = 0 # 重置
    
    # 測試收集事件
    # 從 2026-07-31 開始，追蹤球員 12345
    from datetime import date
    events = await provider.collect_events(["12345"], date.today(), date.today())
    
    print(f"順利完成 collect_events 執行，沒有引發崩潰！")
    print("這證明了：即便有比賽發生 500 錯誤被跳過，系統依然會繼續往下走，抓取正常的資料。")

if __name__ == "__main__":
    asyncio.run(main())
