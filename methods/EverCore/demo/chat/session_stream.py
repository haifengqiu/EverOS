"""Conversation Session Management - Streaming Version

Extends ChatSession with streaming LLM generation for faster first response.
"""

import json
import httpx
import time
import asyncio
from typing import List, Dict, Any, Optional, Tuple, AsyncGenerator
from datetime import timedelta
from pathlib import Path

from demo.config import ChatModeConfig, LLMConfig, ScenarioType
from demo.utils import query_memcells_by_group_and_time
from demo.ui import I18nTexts
from common_utils.cli_ui import CLIUI
from memory_layer.llm.llm_provider import LLMProvider
from common_utils.datetime_utils import get_now_with_timezone, to_iso_format
from memory_layer.memory_extractor.profile_memory_life.types import ProfileMemoryLife


class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    NC = "\033[0m"


class ChatSessionStream:
    """Conversation Session Manager with Streaming LLM"""

    def __init__(
        self,
        group_id: str,
        config: ChatModeConfig,
        llm_config: LLMConfig,
        scenario_type: ScenarioType,
        retrieval_mode: str,
        data_source: str,
        texts: I18nTexts,
        user_id: str = "user_001",
        use_simple_prompt: bool = True,  # Use simplified prompt (no reasoning)
    ):
        self.group_id = group_id
        self.user_id = user_id
        self.config = config
        self.llm_config = llm_config
        self.scenario_type = scenario_type
        self.retrieval_mode = retrieval_mode
        self.data_source = data_source
        self.texts = texts
        self.use_simple_prompt = use_simple_prompt

        self.conversation_history: List[Tuple[str, str]] = []
        self.memcell_count: int = 0
        self.last_latency_profile: Optional[Dict[str, float]] = None

        self.llm_provider: Optional[LLMProvider] = None
        self.api_base_url = config.api_base_url
        self.retrieve_url = f"{self.api_base_url}/api/v1/memories/search"
        self.last_retrieval_metadata: Optional[Dict[str, Any]] = None

    async def initialize(self) -> bool:
        """Initialize session"""
        try:
            display_name = (
                "group_chat" if self.group_id == "AI产品群" else self.group_id
            )
            print(
                f"\n[{self.texts.get('loading_label')}] {self.texts.get('loading_group_data', name=display_name)}"
            )

            await self._check_api_server()

            now = get_now_with_timezone()
            start_date = now - timedelta(days=self.config.time_range_days)
            memcells = await query_memcells_by_group_and_time(
                self.group_id, start_date, now
            )
            self.memcell_count = len(memcells)
            print(
                f"[{self.texts.get('loading_label')}] {self.texts.get('loading_memories_success', count=self.memcell_count)} ✅"
            )

            loaded_history_count = await self.load_conversation_history()
            if loaded_history_count > 0:
                print(
                    f"[{self.texts.get('loading_label')}] {self.texts.get('loading_history_success', count=loaded_history_count)} ✅"
                )
            else:
                print(
                    f"[{self.texts.get('loading_label')}] {self.texts.get('loading_history_new')} ✅"
                )

            self.llm_provider = LLMProvider(
                self.llm_config.provider,
                model=self.llm_config.model,
                api_key=self.llm_config.api_key,
                base_url=self.llm_config.base_url,
                temperature=self.llm_config.temperature,
                max_tokens=self.llm_config.max_tokens,
            )

            print(
                f"\n[{self.texts.get('hint_label')}] {self.texts.get('loading_help_hint')}\n"
            )
            return True

        except Exception as e:
            print(
                f"\n[{self.texts.get('error_label')}] {self.texts.get('session_init_error', error=str(e))}"
            )
            import traceback

            traceback.print_exc()
            return False

    async def _check_api_server(self) -> None:
        """Check if API server is running"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.api_base_url}/docs")
                if response.status_code >= 500:
                    raise ConnectionError("API Server returned error")
        except (httpx.ConnectError, httpx.TimeoutException, ConnectionError) as e:
            error_msg = (
                f"\n❌ Cannot connect to API server: {self.api_base_url}\n\n"
                f"Please start V1 API server first:\n"
                f"  uv run python src/run.py\n\n"
            )
            raise ConnectionError(error_msg) from e

    async def load_conversation_history(self) -> int:
        """Load conversation history from file"""
        try:
            display_name = (
                "group_chat" if self.group_id == "AI产品群" else self.group_id
            )
            history_files = sorted(
                self.config.chat_history_dir.glob(f"{display_name}_*.json"),
                reverse=True,
            )
            if not history_files:
                return 0
            latest_file = history_files[0]
            with latest_file.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
            history = data.get("conversation_history", [])
            self.conversation_history = [
                (item["user_input"], item["assistant_response"])
                for item in history[-self.config.conversation_history_size :]
            ]
            return len(self.conversation_history)
        except Exception as e:
            print(
                f"[{self.texts.get('warning_label')}] {self.texts.get('loading_history_new')}: {e}"
            )
            return 0

    async def save_conversation_history(self) -> None:
        """Save conversation history to file"""
        try:
            display_name = (
                "group_chat" if self.group_id == "AI产品群" else self.group_id
            )
            timestamp = get_now_with_timezone().strftime("%Y-%m-%d_%H-%M")
            filename = f"{display_name}_{timestamp}.json"
            filepath = self.config.chat_history_dir / filename
            data = {
                "group_id": self.group_id,
                "last_updated": get_now_with_timezone().isoformat(),
                "conversation_history": [
                    {
                        "timestamp": get_now_with_timezone().isoformat(),
                        "user_input": user_q,
                        "assistant_response": assistant_a,
                    }
                    for user_q, assistant_a in self.conversation_history
                ],
            }
            with filepath.open("w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)
            print(f"[{self.texts.get('save_label')}] {filename} ✅")
        except Exception as e:
            print(f"[{self.texts.get('error_label')}] {e}")

    async def retrieve_memories(self, query: str) -> Dict[str, List[Dict[str, Any]]]:
        """Retrieve memories (episodes, foresights, profile) in parallel."""
        latency_profile = {
            "episodes_search_ms": 0,
            "foresights_search_ms": 0,
            "profile_fetch_ms": 0,
        }

        async def timed_search(query, memory_types, label):
            start = time.perf_counter()
            result = await self._search(query, memory_types=memory_types)
            elapsed = (time.perf_counter() - start) * 1000
            latency_profile[label] = elapsed
            return result

        async def timed_profile():
            start = time.perf_counter()
            result = await self._fetch_profile()
            elapsed = (time.perf_counter() - start) * 1000
            latency_profile["profile_fetch_ms"] = elapsed
            return result

        tasks = [
            timed_search(query, ["episodic_memory"], "episodes_search_ms"),
            timed_search(query, ["foresight"], "foresights_search_ms"),
            timed_profile(),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_memories = {"episodes": [], "foresights": [], "profiles": []}
        for i, (key, res) in enumerate(
            zip(["episodes", "foresights", "profiles"], results)
        ):
            if isinstance(res, Exception):
                print(f"[Warning] {key}: {res}")
            elif key == "profiles":
                all_memories[key] = res
            else:
                all_memories[key] = self._flatten_result(res)

        total_retrieval_ms = max(
            latency_profile["episodes_search_ms"],
            latency_profile["foresights_search_ms"],
            latency_profile["profile_fetch_ms"],
        )
        latency_profile["total_retrieval_ms"] = total_retrieval_ms
        self.last_latency_profile = latency_profile
        self.last_retrieval_metadata = {
            "retrieval_mode": self.retrieval_mode,
            "total_latency_ms": total_retrieval_ms,
            "episodes_count": len(all_memories["episodes"]),
            "foresights_count": len(all_memories["foresights"]),
            "profiles_count": len(all_memories["profiles"]),
        }
        return all_memories

    def _clean_utf8(self, text: Any) -> Any:
        """Clean UTF-8 surrogate characters from text"""
        if isinstance(text, str):
            try:
                return text.encode("utf-8", errors="replace").decode("utf-8")
            except Exception:
                return str(text).encode("utf-8", errors="replace").decode("utf-8")
        elif isinstance(text, dict):
            return {k: self._clean_utf8(v) for k, v in text.items()}
        elif isinstance(text, list):
            return [self._clean_utf8(item) for item in text]
        return text

    async def _search(
        self,
        query: str,
        memory_types: List[str] = None,
        retrieve_method: str = None,
        top_k: int = None,
        user_id: str = None,
        group_id: str = None,
        timeout: float = 120.0,
    ) -> Dict[str, Any]:
        """Unified search API call"""
        params = {
            "query": query,
            "retrieve_method": retrieve_method or self.retrieval_mode,
            "top_k": top_k or self.config.top_k_memories,
        }
        if user_id:
            params["user_id"] = user_id
        if group_id or self.group_id:
            params["group_id"] = group_id or self.group_id
        if memory_types:
            params["memory_types"] = ",".join(memory_types)

        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            response = await client.get(self.retrieve_url, params=params)
            response.raise_for_status()
            raw_content = response.content.decode("utf-8", errors="replace")
            data = json.loads(raw_content)
            return self._clean_utf8(data)

    async def _fetch_profile(self) -> List[Dict[str, Any]]:
        """Fetch profile via GET /api/v1/memories."""
        url = f"{self.api_base_url}/api/v1/memories"
        params = {"user_id": self.user_id, "memory_type": "profile", "limit": 10}

        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            raw_content = response.content.decode("utf-8", errors="replace")
            data = json.loads(raw_content)
            data = self._clean_utf8(data)

        if data.get("status") != "ok":
            raise RuntimeError(f"API Error: {data.get('message')}")

        memories = data.get("result", {}).get("memories", []) or []
        for mem in memories:
            profile_data = mem.get("profile_data") or {}
            if (
                "readable_profile" not in profile_data
                and "explicit_info" in profile_data
            ):
                profile_data["readable_profile"] = ProfileMemoryLife.from_dict(
                    profile_data
                ).to_readable_profile()
                mem["profile_data"] = profile_data
        return memories

    def _flatten_result(self, resp: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Flatten grouped search result to flat list."""
        if not resp or not isinstance(resp, dict):
            return []
        result = resp.get("result") if isinstance(resp.get("result"), dict) else resp
        if not result:
            return []
        memories = result.get("memories", []) or []
        scores = result.get("scores", []) or []
        if memories and isinstance(memories[0], dict):
            if not any(isinstance(v, list) for v in memories[0].values()):
                return list(memories)
        score_map = {}
        for s in scores:
            if isinstance(s, dict):
                for gid, slist in s.items():
                    if isinstance(slist, list):
                        score_map[gid] = slist
        flat = []
        for grp in memories:
            if not isinstance(grp, dict):
                continue
            for gid, mlist in grp.items():
                if not isinstance(mlist, list):
                    continue
                gscores = score_map.get(gid, [])
                for i, m in enumerate(mlist):
                    if isinstance(m, dict):
                        item = dict(m)
                        if "score" not in item and i < len(gscores):
                            item["score"] = gscores[i]
                        flat.append(item)
        return flat

    def build_prompt(
        self, user_query: str, memories: Dict[str, List[Dict[str, Any]]]
    ) -> str:
        """Build prompt string for LLM (single prompt format for streaming)"""
        messages = []

        # Use simplified prompt if enabled (no reasoning field - faster response)
        lang_key = "zh" if self.texts.language == "zh" else "en"
        if self.use_simple_prompt:
            system_content = self.texts.get(f"prompt_system_role_simple_{lang_key}")
        else:
            system_content = self.texts.get(f"prompt_system_role_{lang_key}")

        if system_content:
            messages.append(f"System: {system_content}")

        memory_sections: List[str] = []

        profiles = memories.get("profiles") or []
        first_profile = profiles[0] if profiles else None
        if isinstance(first_profile, dict):
            profile_text = (first_profile.get("profile_data", {}) or {}).get(
                "readable_profile"
            )
            if profile_text:
                memory_sections.append(f"【User Profile】\n{profile_text}")

        foresights = memories.get("foresights", [])
        if foresights:
            foresight_lines: List[str] = []
            for f in foresights[: self.config.top_k_memories]:
                if not isinstance(f, dict):
                    continue
                content = f.get("foresight") or f.get("summary")
                if content:
                    foresight_lines.append(f"  - {content}")
            if foresight_lines:
                memory_sections.append("【Foresights】\n" + "\n".join(foresight_lines))

        episodes = memories.get("episodes", [])
        if episodes:
            episode_lines: List[str] = []
            for i, mem in enumerate(episodes[: self.config.top_k_memories], start=1):
                if not isinstance(mem, dict):
                    continue
                raw_timestamp = mem.get("timestamp", "")
                iso_timestamp = to_iso_format(raw_timestamp)
                timestamp = iso_timestamp[:10] if iso_timestamp else ""
                content = mem.get("summary") or mem.get("episode") or mem.get("subject")
                if content:
                    episode_lines.append(f"  [{i}] ({timestamp}) {content}")
            if episode_lines:
                memory_sections.append(
                    "【Related Memories】\n" + "\n".join(episode_lines)
                )

        if memory_sections:
            messages.append("System: " + "\n\n".join(memory_sections))

        for user_q, assistant_a in self.conversation_history[
            -self.config.conversation_history_size :
        ]:
            messages.append(f"User: {user_q}")
            messages.append(f"Assistant: {assistant_a}")

        messages.append(f"User: {user_query}")
        messages.append("Assistant:")

        return "\n\n".join(messages)

    async def chat_stream(self, user_input: str) -> str:
        """Core Chat Logic with Streaming LLM - shows incremental output"""
        latency_profile = {"total_ms": 0}

        # 1. Retrieve Memories
        t_retrieve_start = time.perf_counter()
        memories = await self.retrieve_memories(user_input)
        t_retrieve_end = time.perf_counter()
        latency_profile["retrieval_ms"] = (t_retrieve_end - t_retrieve_start) * 1000

        # Show retrieval results (using original ChatUI)
        if self.config.show_retrieved_memories:
            episodes = memories.get("episodes", [])
            foresights = memories.get("foresights", [])
            profiles = memories.get("profiles", [])
            self._print_retrieved_memories_full(episodes, foresights, profiles)

        # 2. Build Prompt
        t_prompt_start = time.perf_counter()
        prompt = self.build_prompt(user_input, memories)
        t_prompt_end = time.perf_counter()
        latency_profile["prompt_build_ms"] = (t_prompt_end - t_prompt_start) * 1000

        # 3. Streaming LLM Generation
        print(f"\n{Colors.CYAN}🤖 Assistant:{Colors.NC} ", end="", flush=True)

        t_llm_start = time.perf_counter()
        first_chunk_time = None
        full_response = ""
        chunk_count = 0

        try:
            async for chunk in self.llm_provider.generate_stream(prompt):
                if first_chunk_time is None:
                    first_chunk_time = time.perf_counter()
                    first_chunk_ms = (first_chunk_time - t_llm_start) * 1000
                    print(
                        f"{Colors.GREEN}[⚡ {first_chunk_ms:.0f}ms]{Colors.NC} ",
                        end="",
                        flush=True,
                    )

                full_response += chunk
                chunk_count += 1
                print(chunk, end="", flush=True)

            t_llm_end = time.perf_counter()
            llm_total_ms = (t_llm_end - t_llm_start) * 1000

            print(f"{Colors.NC}")

            latency_profile["llm_ms"] = llm_total_ms
            latency_profile["llm_first_chunk_ms"] = first_chunk_ms
            latency_profile["llm_chunks"] = chunk_count

        except Exception as e:
            t_llm_end = time.perf_counter()
            latency_profile["llm_ms"] = (t_llm_end - t_llm_start) * 1000
            print(
                f"\n{Colors.RED}[{self.texts.get('error_label')}] {str(e)}{Colors.NC}"
            )
            return f"[{self.texts.get('error_label')}] {str(e)}"

        latency_profile["total_ms"] = (
            latency_profile["retrieval_ms"] + latency_profile["llm_ms"]
        )
        self.last_latency_profile.update(latency_profile)

        # 4. Parse and display response (extract answer from JSON if needed)
        display_response = self._parse_llm_response(full_response)

        # 5. Print latency breakdown with streaming metrics
        self._print_latency_breakdown_streaming(latency_profile)

        # Update conversation history
        self.conversation_history.append((user_input, display_response))
        if len(self.conversation_history) > self.config.conversation_history_size:
            self.conversation_history = self.conversation_history[
                -self.config.conversation_history_size :
            ]

        return display_response

    def _print_retrieved_memories_full(
        self,
        episodes: List[Dict[str, Any]],
        foresights: List[Dict[str, Any]] = None,
        profiles: List[Dict[str, Any]] = None,
    ):
        """Print retrieved memories with full details (matching original chat_with_memory.py UI)"""
        ui = CLIUI()
        from demo.chat.ui import extract_event_time_from_memory

        # Build heading - same format as original
        heading = f"🔍 检索完成"
        total_count = len(episodes)
        if total_count > 0:
            heading += f" - （显示前 {min(total_count, 5)} 条）"

        # Add retrieval mode and latency
        if self.last_retrieval_metadata:
            retrieval_mode = self.last_retrieval_metadata.get("retrieval_mode", "rrf")
            latency_ms = self.last_retrieval_metadata.get("total_latency_ms", 0.0)

            mode_names = {
                "keyword": "Keyword",
                "vector": "Vector",
                "hybrid": "Hybrid",
                "rrf": "RRF",
                "agentic": "Agentic",
            }
            mode_text = mode_names.get(retrieval_mode, retrieval_mode)
            heading += f" | {mode_text} | {int(latency_ms)}ms"

        print()
        ui.section_heading(heading)

        # Agentic mode special info (same as original)
        if (
            self.last_retrieval_metadata
            and self.last_retrieval_metadata.get("retrieval_mode") == "agentic"
        ):
            is_sufficient = self.last_retrieval_metadata.get("is_sufficient")
            if is_sufficient is not None:
                status_icon = "✅" if is_sufficient else "❌"
                status_text = "信息充分" if is_sufficient else "信息不足"
                print(f"  🤖 LLM判断: {status_icon} {status_text}")

            is_multi_round = self.last_retrieval_metadata.get("is_multi_round", False)
            if is_multi_round:
                print(f"  🔄 多轮检索")

        # Display memory list in panel format (matching original)
        lines = []
        for i, mem in enumerate(episodes[:5], start=1):
            if not isinstance(mem, dict):
                continue

            # Extract actual event time
            event_time = extract_event_time_from_memory(mem)

            # Priority: subject > summary > episode > atomic_fact > content
            subject = (mem.get("subject") or "").strip()
            summary = (mem.get("summary") or "").strip()
            episode = (mem.get("episode") or "").strip()
            atomic_fact = (mem.get("atomic_fact") or "").strip()
            content = (mem.get("content") or "").strip()

            # Select first non-empty field
            display_text = (
                subject or summary or episode or atomic_fact or content or "(无内容)"
            )

            # Handle encoding issues
            try:
                display_text = str(display_text)
                display_text = display_text.encode("utf-8", errors="replace").decode(
                    "utf-8"
                )
            except Exception:
                display_text = "(显示错误)"

            # Limit display length
            if len(display_text) > 50:
                display_text = display_text[:47] + "..."

            # Build display line with score
            score = mem.get("score")
            score_text = ""
            if isinstance(score, (int, float)):
                score_text = f"{score:.3f} | "

            # Format: 📌 [i]  date  │  score | text
            if event_time:
                lines.append(f"📌 [{i}]  {event_time}  │  {score_text}{display_text}")
            else:
                lines.append(f"📌 [{i}]  {score_text}{display_text}")

        if lines:
            print()
            ui.panel(lines)
        else:
            print(f"  {Colors.DIM}未找到相关记忆{Colors.NC}")

        print(f"{Colors.DIM}{'─' * 50}{Colors.NC}")

    def _parse_llm_response(self, response: str) -> str:
        """Parse LLM response and extract user-visible content"""
        # Try to parse as JSON
        try:
            data = json.loads(response.strip())
            answer = data.get("answer", "")
            additional_notes = data.get("additional_notes", "")

            # Combine answer and additional_notes (skip reasoning for user display)
            if additional_notes:
                return f"{answer}\n\n💡 {additional_notes}"
            return answer
        except json.JSONDecodeError:
            # Not JSON, return as-is
            return response.strip()

    def _print_retrieved_memories(self, memories: List[Dict[str, Any]]):
        """Print retrieved memories (simplified version)"""
        if not memories:
            return

        print(f"\n{Colors.DIM}{'─' * 50}{Colors.NC}")
        print(f"{Colors.YELLOW}📖 Retrieved Memories:{Colors.NC}")

        for i, mem in enumerate(memories[:5], 1):
            if not isinstance(mem, dict):
                continue
            summary = mem.get("summary") or mem.get("episode") or mem.get("subject", "")
            timestamp = mem.get("timestamp", "")
            if timestamp:
                timestamp = to_iso_format(timestamp)[:10]
            if summary:
                print(f"  {Colors.DIM}[{i}] ({timestamp}){Colors.NC} {summary[:80]}...")

        print(f"{Colors.DIM}{'─' * 50}{Colors.NC}")

    def _print_latency_breakdown_streaming(self, latency: Dict[str, float]):
        """Print latency breakdown with streaming-specific metrics"""
        print(f"\n{Colors.DIM}{'─' * 50}{Colors.NC}")
        print(f"{Colors.BOLD}📊 Latency Breakdown{Colors.NC}")
        print(f"{Colors.DIM}{'─' * 50}{Colors.NC}")

        # Retrieval breakdown
        retrieval_ms = latency.get("retrieval_ms", 0)
        if self.last_latency_profile:
            episodes_ms = self.last_latency_profile.get("episodes_search_ms", 0)
            foresights_ms = self.last_latency_profile.get("foresights_search_ms", 0)
            profile_ms = self.last_latency_profile.get("profile_fetch_ms", 0)
            print(f"  🔍 Retrieval:       {retrieval_ms:.1f} ms")
            print(f"     Episodes:       {episodes_ms:.1f} ms")
            print(f"     Foresights:     {foresights_ms:.1f} ms")
            print(f"     Profile:        {profile_ms:.1f} ms")

        print(f"  📝 Prompt Build:    {latency.get('prompt_build_ms', 0):.1f} ms")

        # LLM with streaming metrics
        first_chunk_ms = latency.get("llm_first_chunk_ms", 0)
        llm_total_ms = latency.get("llm_ms", 0)
        chunks = latency.get("llm_chunks", 0)

        print(f"\n  {Colors.CYAN}⚡ LLM Streaming:{Colors.NC}")
        print(
            f"     {Colors.GREEN}First chunk:     {first_chunk_ms:.1f} ms{Colors.NC}  (user sees response here)"
        )
        print(f"     Total:          {llm_total_ms:.1f} ms")
        print(f"     Chunks:         {chunks}")

        # Streaming benefit calculation
        if llm_total_ms > first_chunk_ms and first_chunk_ms > 0:
            saved_ms = llm_total_ms - first_chunk_ms
            speedup = llm_total_ms / first_chunk_ms
            print(f"\n  {Colors.HEADER}💡 Streaming Benefit:{Colors.NC}")
            print(
                f"     Perceived latency: {Colors.GREEN}{first_chunk_ms:.1f} ms{Colors.NC} (vs {llm_total_ms:.1f} ms non-streaming)"
            )
            print(
                f"     User sees response {Colors.CYAN}{speedup:.1f}x{Colors.NC} faster"
            )

        print(f"\n  ⏱️  Total (R+L):    {latency.get('total_ms', 0):.1f} ms")
        print(f"{Colors.DIM}{'─' * 50}{Colors.NC}")

    def clear_history(self) -> None:
        """Clear conversation history"""
        count = len(self.conversation_history)
        self.conversation_history = []
        print(f"{Colors.GREEN}✓ History cleared ({count} messages){Colors.NC}")

    async def reload_data(self) -> None:
        """Reload memory data"""
        display_name = "group_chat" if self.group_id == "AI产品群" else self.group_id
        print(f"\n{Colors.YELLOW}🔄 Refreshing data for {display_name}...{Colors.NC}")

        now = get_now_with_timezone()
        start_date = now - timedelta(days=self.config.time_range_days)
        memcells = await query_memcells_by_group_and_time(
            self.group_id, start_date, now
        )
        self.memcell_count = len(memcells)

        print(f"{Colors.GREEN}✓ Reloaded: {self.memcell_count} memories{Colors.NC}")
