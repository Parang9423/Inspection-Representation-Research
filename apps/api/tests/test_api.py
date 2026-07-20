import importlib
import os
from pathlib import Path
from fastapi.testclient import TestClient

def load_app(tmp_path: Path):
    os.environ['AOI_DATA_ROOT']=str(tmp_path/'split_image')
    os.environ['AOI_CAM_ROOT']=str(tmp_path/'cam_image')
    os.environ['AOI_EXPORT_ROOT']=str(tmp_path/'exports')
    os.environ['AOI_DB_PATH']=str(tmp_path/'dataset.db')
    import app.main as main
    importlib.reload(main)
    return main

def test_summary_and_split(tmp_path):
    main=load_app(tmp_path)
    label_dir=Path(os.environ['AOI_DATA_ROOT'])/'D01'; label_dir.mkdir(parents=True)
    (label_dir/'sample.png').write_bytes(b'not-a-real-image')
    main.init_db(); main.scan_images(); client=TestClient(main.app)
    summary=client.get('/api/summary'); assert summary.status_code==200; assert summary.json()['totals']['total']==1
    result=client.post('/api/splits/auto',json={'train_ratio':100,'valid_ratio':0,'test_ratio':0}); assert result.status_code==200; assert result.json()['updated']==1
