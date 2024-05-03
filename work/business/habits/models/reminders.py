from core.web.services.core.json import JsonObject


priority_quadrants = {
    'Q1': ['IMPORTANT', 'URGENT'],
    'Q2': ['IMPORTANT'],
    'Q3': ['URGENT'],
    'Q4': [],
}


def get_habits_quadrant_priority(search_list: []):
    for key in priority_quadrants.keys():
        check = all(item in search_list for item in priority_quadrants[key])
        if check:
            return key


class DtoTaskReminder(JsonObject):
    name: str = ''
    description: str = ''
    completed: bool = False
    points: int = 0
    tags: list = []
    roles: list = []
    priority: str = ''
    url: str = ''



