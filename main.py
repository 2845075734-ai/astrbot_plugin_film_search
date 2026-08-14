import aiohttp
import astrbot.api.message_components as Comp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger
from astrbot.api import AstrBotConfig


class FilmSearch(Star):
    """影视资源搜索插件，支持LLM自动调用和手动指令两种使用方式"""

    BASE_URL = "https://api-v2.yuafeng.cn/API/filmSearch.php"

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.apikey = self.config.get("apikey", "").strip()
        self.max_results = self.config.get("max_results", 0)  # 0 表示不限制
        
        if self.apikey:
            logger.info(f"[film_search] ✅ 配置读取成功，API Key: {self.apikey[:4]}****")
        else:
            logger.warning("[film_search] ⚠️ 未配置 API Key，将使用免费额度（可能受限）")

    async def _request_api(self, params: dict) -> dict:
        """异步请求 API，自动携带配置的 Key"""
        if self.apikey:
            params["apikey"] = self.apikey
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.BASE_URL, 
                    params=params, 
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status != 200:
                        return {"code": -1, "msg": f"HTTP错误: {resp.status}"}
                    return await resp.json()
        except Exception as e:
            logger.error(f"[film_search] API请求失败: {e}")
            return {"code": -1, "msg": str(e)}

    async def _search_films(self, msg: str) -> tuple[list, str]:
        """搜索影视"""
        result = await self._request_api({"msg": msg})
        if result.get("code") == 0:
            data = result.get("data")
            if isinstance(data, list):
                return data, ""
            elif isinstance(data, dict):
                return [data], ""
            return [], "数据格式异常"
        return [], result.get("msg", "未知错误")

    async def _get_film_by_id(self, film_id: int) -> tuple[dict, str]:
        """按ID查询"""
        result = await self._request_api({"id": film_id})
        if result.get("code") == 0:
            data = result.get("data")
            if isinstance(data, dict):
                return data, ""
            elif isinstance(data, list) and data:
                return data[0], ""
            return {}, "数据格式异常"
        return {}, result.get("msg", "未知错误")

    # ==================== 🔍 调试指令 ====================
    @filter.command("filmdebug")
    async def film_debug(self, event: AstrMessageEvent):
        """调试：查看配置和API状态"""
        lines = ["🔍 FilmSearch 调试信息："]
        lines.append(f"✅ API Key 已读取: {'是' if self.apikey else '否'}")
        lines.append(f"🔑 Key 长度: {len(self.apikey)}")
        lines.append(f"📊 最大返回条数: {'不限制' if self.max_results == 0 else self.max_results}")
        
        lines.append("\n🌐 测试 API 调用（搜索'哪吒'）...")
        films, err = await self._search_films("哪吒")
        if err:
            lines.append(f"❌ API 返回错误: {err}")
        else:
            lines.append(f"✅ API 调用成功，找到 {len(films)} 条结果")
            if films:
                lines.append(f"   第一条: {films[0].get('title', '未知')}")

        yield event.plain_result("\n".join(lines))

    # ==================== LLM 自动调用工具 ====================
    @filter.llm_tool(name="search_film")
    async def search_film(self, event: AstrMessageEvent, keyword: str) -> str:
        '''搜索影视资源信息。

        Args:
            keyword(string): 影视名称或关键词，例如"哪吒之魔童闹海"、"变形金刚3"
        '''
        keyword = keyword.strip()
        if not keyword:
            return "请提供要搜索的影视名称。"

        film_list, error_msg = await self._search_films(keyword)
        
        if error_msg:
            if "apikey" in error_msg.lower():
                return f"搜索失败：{error_msg}。请在 AstrBot 管理面板的 film_search 插件配置中填写 API Key。"
            return f"搜索失败：{error_msg}"

        if not film_list:
            return f"未找到与「{keyword}」相关的影视资源。"

        # 根据配置决定返回数量，0 表示返回全部
        if self.max_results > 0:
            items = film_list[:self.max_results]
            total_text = f"（共找到 {len(film_list)} 条，展示前 {len(items)} 条）"
        else:
            items = film_list
            total_text = f"（共找到 {len(film_list)} 条，展示全部）"

        text = f"搜索「{keyword}」的结果{total_text}：\n\n"
        for i, film in enumerate(items, 1):
            title = film.get("title", "未知")
            year = film.get("publish_date", "未知")
            score = film.get("douban_score", "暂无")
            desc = film.get("desc", film.get("content", "暂无简介"))
            if len(desc) > 200:
                desc = desc[:200] + "..."
            
            text += f"【{i}】《{title}》({year}) ⭐{score}\n"
            text += f"导演: {film.get('director', '未知')} | 类型: {film.get('class', '未知')}\n"
            text += f"简介: {desc}\n"
            
            videos = film.get("video_list", [])
            if videos:
                text += "播放链接:\n"
                for v in videos:  # 返回全部播放链接
                    url = v.get("m3u8") or v.get("mp4", "")
                    if url:
                        text += f"  - {v.get('tag', '未知')}: {url}\n"
            text += "\n"
        return text

    # ==================== 手动指令组 ====================
    @filter.command_group("film")
    def film_group(self):
        """影视搜索指令组，包含搜索、详情、播放等功能"""
        pass

    @film_group.command("search")
    async def film_search_cmd(self, event: AstrMessageEvent, keyword: str):
        """搜索影视资源：/film search <片名>"""
        film_list, error_msg = await self._search_films(keyword.strip())
        if error_msg:
            yield event.plain_result(f"❌ 搜索失败：{error_msg}")
            return
        if not film_list:
            yield event.plain_result(f"❌ 未找到「{keyword}」相关资源")
            return

        # 缓存搜索结果
        cache = self.context.get_global_config().get("film_search_cache", {})
        cache[f"{event.get_sender_id()}_last_search"] = film_list
        self.context.get_global_config()["film_search_cache"] = cache

        # 根据配置决定返回数量
        if self.max_results > 0:
            items = film_list[:self.max_results]
            total_text = f"找到 {len(film_list)} 条，展示前 {len(items)} 条"
        else:
            items = film_list
            total_text = f"找到 {len(film_list)} 条，展示全部"

        text = f"🔍 搜索「{keyword}」{total_text}：\n" + "─" * 30 + "\n"
        for i, f in enumerate(items, 1):
            text += f"【{i}】{f.get('title', '?')} ({f.get('publish_date', '?')}) ⭐{f.get('douban_score', '?')}\n"
        text += "─" * 30 + "\n💡 /film detail <序号> | /film play <序号>"

        chain = []
        if film_list[0].get("cover"):
            chain.append(Comp.Image.fromURL(film_list[0]["cover"]))
        chain.append(Comp.Plain(text))
        yield event.chain_result(chain)

    @film_group.command("detail")
    async def film_detail_cmd(self, event: AstrMessageEvent, num_or_id: str):
        """查看影视详情：/film detail <序号或ID>"""
        if not num_or_id.isdigit():
            yield event.plain_result("❌ 请输入数字序号或ID")
            return
        
        num = int(num_or_id)
        film = None
        
        # 查缓存
        cache = self.context.get_global_config().get("film_search_cache", {})
        ck = f"{event.get_sender_id()}_last_search"
        if ck in cache and 0 <= num - 1 < len(cache[ck]):
            film, err = await self._get_film_by_id(cache[ck][num - 1].get("id"))
            if err:
                yield event.plain_result(f"❌ {err}")
                return
        
        # 直接查ID
        if not film:
            film, err = await self._get_film_by_id(num)
            if err:
                yield event.plain_result(f"❌ {err}")
                return
            if not film:
                yield event.plain_result(f"❌ 未找到 {num}")
                return

        text = f"🎬 《{film.get('title', '未知')}》\n" + "═" * 30 + "\n"
        text += f"📅 {film.get('publish_date', '?')} | 🌍 {film.get('publish_area', '?')} | 🎭 {film.get('language', '?')}\n"
        text += f"🏷️ {film.get('class', '?')} | ⭐ {film.get('douban_score', '?')}\n"
        text += f"🎬 导演: {film.get('director', '?')} | ✍️ 编剧: {film.get('writer', '?')}\n"
        text += f"👤 演员: {film.get('actor', '未知')[:80]}\n"
        text += "─" * 30 + "\n"
        desc = film.get("desc", film.get("content", "暂无简介"))
        if len(desc) > 300: desc = desc[:300] + "..."
        text += f"📝 {desc}\n"

        chain = []
        if film.get("cover"):
            chain.append(Comp.Image.fromURL(film["cover"]))
        chain.append(Comp.Plain(text))
        yield event.chain_result(chain)

    @film_group.command("play")
    async def film_play_cmd(self, event: AstrMessageEvent, num_or_id: str):
        """获取播放链接：/film play <序号或ID>"""
        if not num_or_id.isdigit():
            yield event.plain_result("❌ 请输入数字")
            return
        
        num = int(num_or_id)
        film = None
        
        cache = self.context.get_global_config().get("film_search_cache", {})
        ck = f"{event.get_sender_id()}_last_search"
        if ck in cache and 0 <= num - 1 < len(cache[ck]):
            film, err = await self._get_film_by_id(cache[ck][num - 1].get("id"))
            if err:
                yield event.plain_result(f"❌ {err}")
                return
        
        if not film:
            film, err = await self._get_film_by_id(num)
            if err:
                yield event.plain_result(f"❌ {err}")
                return
            if not film:
                yield event.plain_result(f"❌ 未找到 {num}")
                return

        vl = film.get("video_list", [])
        if not vl:
            yield event.plain_result(f"❌ 《{film.get('title', '?')}》暂无播放链接")
            return

        text = f"🎬 《{film.get('title', '未知')}》播放链接（共 {len(vl)} 集）\n" + "─" * 30 + "\n"
        for v in vl:  # 返回全部播放链接
            text += f"📺 {v.get('tag', '?')}\n"
            if v.get("m3u8"): text += f"  🔗 流媒体: {v['m3u8']}\n"
            if v.get("mp4"): text += f"  📥 下载: {v['mp4']}\n"
        yield event.plain_result(text)

    async def terminate(self):
        logger.info("FilmSearch 插件已卸载")
