import json
from pathlib import Path


class MemoryManager:

    def __init__(self):

        self.memory_file = Path("memory/memory.json")

        if not self.memory_file.exists():
            self.memory_file.write_text("{}")

    def load(self):

        with open(self.memory_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, data):

        with open(self.memory_file, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=4
            )

    def remember(self, key, value):
        data = self.load()
        data[key] = value
        self.save(data)


    def recall(self, key):
        data = self.load()
        return data.get(key)
    
    def forget(self, key):
        data = self.load()

        if key in data:
            del data[key]
            self.save(data)
            return True

        return False