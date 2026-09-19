import os,sys
from pathlib import Path
workspace=Path(r'C:/Users/brian/GIT/harqis-work')
reference=Path(r'C:/Users/brian/GIT/harqis-work-main-reference')
sys.path.insert(0,str(workspace))
from scripts.deploy import load_env_into_os,load_machine_config,machine_env_vars
load_env_into_os()
os.environ.update(machine_env_vars(load_machine_config(None)))
from dotenv import load_dotenv
load_dotenv(workspace/'frontend'/'.env',override=True)
os.environ.setdefault('APP_CONFIG_FILE','apps_config.yaml')
os.environ.setdefault('WORKFLOW_CONFIG','workflows.config')
os.chdir(reference)
sys.path=[str(reference/'frontend'),str(reference)]+[p for p in sys.path if p!=str(workspace)]
os.environ['ROOT_DIRECTORY']=str(reference)
os.environ['PATH_APP_CONFIG']=str(reference)
import uvicorn
uvicorn.run('main:app',host='127.0.0.1',port=8093,access_log=False)
