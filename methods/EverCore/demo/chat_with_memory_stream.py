"""Memory Enhanced Chat Script - Streaming Version

Interactive chat with memory retrieval and streaming LLM generation.

Usage:
    uv run python src/bootstrap.py demo/chat_with_memory_stream.py

Alternative:
    cd demo
    python chat_with_memory_stream.py
"""

import asyncio
from pathlib import Path
from datetime import timedelta

from dotenv import load_dotenv
from demo.chat.session_stream import ChatSessionStream
from demo.config import ChatModeConfig, LLMConfig, MongoDBConfig, ScenarioType
from demo.utils import ensure_mongo_beanie_ready
from demo.ui import I18nTexts
from demo.chat.ui import ChatUI
from demo.chat.selectors import LanguageSelector, ScenarioSelector, GroupSelector
from common_utils.cli_ui import CLIUI
from common_utils.datetime_utils import get_now_with_timezone

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    NC = "\033[0m"


class StreamChatOrchestrator:
    """Streaming Chat Application Orchestrator"""

    def __init__(self, project_root: Path):
        self.project_root = project_root

    async def select_language(self) -> I18nTexts:
        """Language selection"""
        ChatUI.clear_screen()
        print(f"\n{Colors.HEADER}{Colors.BOLD}{'=' * 60}{Colors.NC}")
        print(
            f"{Colors.HEADER}{Colors.BOLD}  🌏  语言选择 / Language Selection{Colors.NC}"
        )
        print(f"{Colors.HEADER}{Colors.BOLD}{'=' * 60}{Colors.NC}")
        print()
        print("  [1] 中文 (Chinese)")
        print("  [2] English")
        print()
        print("  💡 提示：为获得最佳体验，建议记忆数据与选择的语言保持一致")

        while True:
            try:
                choice = input("请选择语言 / Please select language [1-2]: ").strip()
                if choice == "1":
                    return I18nTexts("zh")
                elif choice == "2":
                    return I18nTexts("en")
                else:
                    print(f"{Colors.RED}无效选择，请输入 1 或 2{Colors.NC}")
            except KeyboardInterrupt:
                raise

    async def select_scenario(self, texts: I18nTexts) -> str:
        """Scenario selection"""
        ChatUI.clear_screen()
        ChatUI.print_banner(texts)

        print()
        print(f"  [1] {texts.get('scenario_assistant')}")
        print(f"  [2] {texts.get('scenario_group_chat')}")
        print()

        while True:
            try:
                choice = input(f"{texts.get('scenario_prompt')}: ").strip()
                if choice == "1":
                    return "assistant"
                elif choice == "2":
                    return "group_chat"
                else:
                    print(f"{Colors.RED}{texts.get('invalid_input_number')}{Colors.NC}")
            except KeyboardInterrupt:
                raise

    async def select_group(self, texts: I18nTexts) -> str:
        """Group selection"""
        from demo.chat.selectors import GroupSelector
        from demo.chat.ui import ChatUI

        groups = await GroupSelector.list_available_groups()

        if not groups:
            print(f"{Colors.YELLOW}未找到任何群组数据，使用默认群组{Colors.NC}")
            return "default_group"

        selected_group_id = await GroupSelector.select_group(groups, texts)

        if not selected_group_id:
            raise KeyboardInterrupt()

        return selected_group_id

    async def select_retrieval_mode(self, texts: I18nTexts) -> str:
        """Retrieval mode selection"""
        ui = CLIUI()
        print()
        ui.section_heading(texts.get("retrieval_mode_selection_title"))
        print()
        print(
            f"  [1] {texts.get('retrieval_mode_keyword')} - {texts.get('retrieval_mode_keyword_desc')}"
        )
        print(
            f"  [2] {texts.get('retrieval_mode_vector')} - {texts.get('retrieval_mode_vector_desc')}"
        )
        print(
            f"  [3] {texts.get('retrieval_mode_hybrid')} - {texts.get('retrieval_mode_hybrid_desc')}"
        )
        print(
            f"  [4] {texts.get('retrieval_mode_rrf')} - {texts.get('retrieval_mode_rrf_desc')}"
        )
        print()

        mode_map = {1: "keyword", 2: "vector", 3: "hybrid", 4: "rrf"}

        while True:
            try:
                choice = input(f"{texts.get('retrieval_mode_prompt')}: ").strip()
                index = int(choice)
                if index in mode_map:
                    return mode_map[index]
                else:
                    print(
                        f"{Colors.RED}{texts.get('retrieval_mode_invalid_range')}{Colors.NC}"
                    )
            except ValueError:
                print(f"{Colors.RED}{texts.get('invalid_input_number')}{Colors.NC}")
            except KeyboardInterrupt:
                raise

    async def create_session(
        self,
        group_id: str,
        scenario_type: str,
        retrieval_mode: str,
        texts: I18nTexts,
    ) -> ChatSessionStream:
        """Create and initialize streaming session"""
        chat_config = ChatModeConfig()
        llm_config = LLMConfig()

        # Extract user_id from group_id
        user_id = "user_001"
        if "_" in group_id:
            parts = group_id.split("_")
            for i, part in enumerate(parts):
                if part == "user" and i + 1 < len(parts):
                    user_id = f"user_{parts[i + 1]}"
                    break

        session = ChatSessionStream(
            group_id=group_id,
            config=chat_config,
            llm_config=llm_config,
            scenario_type=ScenarioType(scenario_type),
            retrieval_mode=retrieval_mode,
            data_source="episodic_memory",
            texts=texts,
            user_id=user_id,
        )

        if not await session.initialize():
            raise RuntimeError(texts.get("session_init_failed"))

        return session

    async def run_chat_loop(self, session: ChatSessionStream, texts: I18nTexts):
        """Run conversation loop with streaming"""
        ChatUI.clear_screen()
        ChatUI.print_banner(texts)

        ui = CLIUI()
        print()
        ui.rule()
        ui.note(f"{texts.get('chat_start_note')} (Streaming Mode)", icon="💬")
        ui.rule()
        print()

        print(f"{Colors.CYAN}提示：响应将流式显示，您会更快看到首个回复{Colors.NC}")
        print(
            f"{Colors.DIM}命令: 'exit' 退出, 'clear' 清空历史, 'reload' 重载记忆{Colors.NC}"
        )
        print()

        while True:
            try:
                print(f"{Colors.BOLD}👤 You:{Colors.NC} ", end="")
                user_input = input().strip()

                if not user_input:
                    continue

                command = user_input.lower()

                if command == "exit":
                    print()
                    ui.note(texts.get("cmd_exit_saving"), icon="💾")
                    await session.save_conversation_history()
                    print()
                    ui.success(f"✓ {texts.get('cmd_exit_complete')}")
                    break
                elif command == "clear":
                    session.clear_history()
                    continue
                elif command == "reload":
                    await session.reload_data()
                    continue

                # Streaming chat with memory retrieval
                response = await session.chat_stream(user_input)

            except KeyboardInterrupt:
                print("\n")
                ui.note(texts.get("cmd_interrupt_saving"), icon="⚠️")
                await session.save_conversation_history()
                print()
                ui.success(f"✓ {texts.get('cmd_exit_complete')}")
                break

            except Exception as e:
                print(f"\n{Colors.RED}[{texts.get('error_label')}] {str(e)}{Colors.NC}")
                import traceback

                traceback.print_exc()
                print()

    async def run(self):
        """Run streaming chat application"""
        # 1. Language selection
        texts = await self.select_language()

        # 2. Scenario selection
        scenario_type = await self.select_scenario(texts)

        # 3. Clear screen
        ChatUI.clear_screen()
        ChatUI.print_banner(texts)

        # 4. Initialize database
        mongo_config = MongoDBConfig()
        try:
            await ensure_mongo_beanie_ready(mongo_config)
        except Exception as e:
            ChatUI.print_error(texts.get("mongodb_init_failed", error=str(e)), texts)
            return

        # 5. Group selection
        try:
            group_id = await self.select_group(texts)
        except KeyboardInterrupt:
            print("\n")
            return

        # 6. Retrieval mode selection
        try:
            retrieval_mode = await self.select_retrieval_mode(texts)
        except KeyboardInterrupt:
            print("\n")
            return

        # 7. Create session
        try:
            session = await self.create_session(
                group_id, scenario_type, retrieval_mode, texts
            )
        except Exception as e:
            ChatUI.print_error(str(e), texts)
            return

        # 8. Run conversation loop
        await self.run_chat_loop(session, texts)


async def main():
    """Main Entry - Start Chat Application"""
    orchestrator = StreamChatOrchestrator(PROJECT_ROOT)
    await orchestrator.run()


if __name__ == "__main__":
    asyncio.run(main())
