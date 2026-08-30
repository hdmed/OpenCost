import unittest, json, sys, os, tempfile, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from extract import load_json, fetch_sessions

class TestLoadJson(unittest.TestCase):
    def test_corrupt_backup(self):
        with tempfile.TemporaryDirectory() as d:
            p=os.path.join(d,"a.json")
            open(p,"w").write("{bad")
            v=load_json(p, {"x":1})
            self.assertEqual(v, {"x":1})
            self.assertTrue(any(f.startswith("a.json.corrupt.") for f in os.listdir(d)))

    def test_missing_returns_default(self):
        self.assertEqual(load_json("/no/such/file.json", 42), 42)

class TestFetch(unittest.TestCase):
    def test_fetch_coalesce(self):
        with tempfile.TemporaryDirectory() as d:
            db=os.path.join(d,"t.db")
            conn=sqlite3.connect(db)
            conn.execute("CREATE TABLE session (id TEXT PRIMARY KEY, project_id TEXT, directory TEXT, title TEXT, agent TEXT, model TEXT, cost REAL, tokens_input INT, tokens_output INT, tokens_reasoning INT, tokens_cache_read INT, tokens_cache_write INT, time_created INT, time_updated INT)")
            conn.execute("CREATE TABLE project (id TEXT PRIMARY KEY, name TEXT, worktree TEXT)")
            conn.execute("INSERT INTO session VALUES ('a','p1','','t','ag','{}',1,0,0,0,0,0,1000,NULL)".replace("{}", json.dumps({"providerID":"opencode","id":"m"})))
            conn.execute("INSERT INTO session VALUES ('b','p1','','t','ag','{}',1,0,0,0,0,0,2000,2000)".replace("{}", json.dumps({"providerID":"opencode","id":"m"})))
            conn.commit(); conn.close()
            rows=fetch_sessions(db, 1500, False)
            ids={r["id"] for r in rows}
            self.assertIn("b", ids)  # time_updated 2000 > 1500
            # a has NULL time_updated -> COALESCE uses time_created 1000 -> 1000 >1500 false, not fetched (fix)
            self.assertNotIn("a", ids)

if __name__=="__main__":
    unittest.main()
