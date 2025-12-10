#!/usr/bin/env python
from core.apps.sprout.manage import main as sprout_main

from core.apps.sprout.settings import APP_PACKAGE
from core.config.env_variables import ENV_WORKFLOW_CONFIG
#from core.config.env_variables import ENV_WORKFLOW_CONCURRENCY
from core.config.env_variables import ENV_WORKFLOW_QUEUE
print('====================================================================================')
print(f'{APP_PACKAGE}')
print(f'{ENV_WORKFLOW_CONFIG}')
#print(f'{ENV_WORKFLOW_CONCURRENCY}')
print(f'{ENV_WORKFLOW_QUEUE}')
print('====================================================================================')

if __name__ == '__main__':
    sprout_main()
