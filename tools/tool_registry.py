from tools.app_tool import AppTool
from tools.file_tool import FileTool
from tools.rag_tool import RagTool
from tools.apply_changes_tool import ApplyChangesTool
from tools.debug_agent_tool import DebugAgentTool
from tools.static_analyzer_tool import StaticAnalyzerTool
from tools.project_file_selector import ProjectFileSelector
from tools.dead_code_tool import DeadCodeTool


class ToolRegistry:

    def __init__(self, provider_router=None):

        self.app_tool = AppTool()
        self.file_tool = FileTool()
        self.rag_tool = RagTool()
        self.apply_changes_tool = ApplyChangesTool()
        self.debug_agent_tool = DebugAgentTool(self, provider_router)
        self.static_analyzer_tool = StaticAnalyzerTool()
        self.project_file_selector = ProjectFileSelector()
        self.dead_code_tool = DeadCodeTool()

        self.tools = {
            "open_app": self.app_tool.open_app,
            "create_file": self.file_tool.create_file,
            "read_file": self.file_tool.read_file,
            "list_folder": self.file_tool.list_folder,
            "append_file": self.file_tool.append_file,
            "search_files": self.file_tool.search_files,
            "search_text": self.file_tool.search_text,
            "read_file_preview": self.file_tool.read_file_preview,
            "read_folder_context": self.file_tool.read_folder_context,
            "search_project_rag": self.rag_tool.search_project,
            "index_project_rag": self.rag_tool.index_project,
            "apply_change": self.apply_changes_tool.apply_pending_change,
            "cancel_change": self.apply_changes_tool.cancel_pending_change,
            "show_pending_change": self.apply_changes_tool.show_pending_change,
            "debug_project": self.debug_agent_tool.debug_project,
            "review_file_deep": self.debug_agent_tool.review_file_deep,
            "analyze_static": self.static_analyzer_tool.analyze_file,
            "analyze_folder_static": self.static_analyzer_tool.analyze_folder,
            "select_project_files": self.project_file_selector.select_files,
            "review_project_files": self.debug_agent_tool.review_project_files,
            "detect_dead_code": self.dead_code_tool.detect_dead_code,
        }

    def execute(self, action, **kwargs):

        tool = self.tools.get(action)

        if not tool:
            return None

        return tool(**kwargs)
    
    def get_apply_changes_tool(self):
        return self.apply_changes_tool