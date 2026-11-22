"""A malformed or interrupted replacement must preserve the user's valid input."""
import http.client
import threading

import pytest

from pitopt.ui.server import App, UIServer, make_handler


@pytest.mark.parametrize('mode', ['malformed', 'interrupted', 'empty', 'nonfinite'])
def test_failed_upload_preserves_existing_source(tmp_path, mode):
    folder = tmp_path / 'projects' / 'audit' / 'data'
    folder.mkdir(parents=True)
    target = folder / 'blocks.csv'
    original = b'X,Y,Z,CU\n0,0,0,1\n'
    target.write_bytes(original)
    server = UIServer(('127.0.0.1', 0), make_handler(App(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
    try:
        payload = {'malformed': b'"unclosed', 'interrupted': b'X,Y,Z,CU\n',
                   'empty': b'X,Y,Z,CU\n', 'nonfinite': b'X,Y,Z,CU\ninf,0,0,1\n'}[mode]
        conn.putrequest('POST', '/api/upload?project=audit&name=blocks.csv')
        conn.putheader('X-PitOpt', '1')
        conn.putheader('Content-Length', str(len(payload) + (100 if mode == 'interrupted' else 0)))
        conn.endheaders(payload)
        if mode == 'interrupted':
            import socket

            conn.sock.shutdown(socket.SHUT_WR)
        response = conn.getresponse()
        assert response.status == 400, response.read()
        response.read()
        assert target.read_bytes() == original
        assert list(folder.iterdir()) == [target]
    finally:
        conn.close()
        server.shutdown()
        server.server_close()
        thread.join()


def test_upload_rejects_oversized_payload_413_and_symlink_and_demo_project(tmp_path):
    from pitopt.ui.server import MAX_UPLOAD

    folder = tmp_path / "projects" / "audit" / "data"
    folder.mkdir(parents=True)
    outside = tmp_path / "outside.csv"
    outside.write_text("X,Y,Z,CU\n0,0,0,1\n")
    (folder / "link.csv").symlink_to(outside)

    server = UIServer(("127.0.0.1", 0), make_handler(App(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # 1. Oversized Content-Length -> 413 without streaming body
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        conn.putrequest("POST", "/api/upload?project=audit&name=big.csv")
        conn.putheader("X-PitOpt", "1")
        conn.putheader("Content-Length", str(MAX_UPLOAD + 1))
        conn.endheaders(b"")
        assert conn.getresponse().status == 413
        conn.close()

        # 2. Symlink target in data/ -> 403
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        conn.request("POST", "/api/upload?project=audit&name=link.csv", body=b"X,Y,Z,CU\n0,0,0,1\n", headers={"X-PitOpt": "1"})
        assert conn.getresponse().status == 403
        conn.close()

        # 3. Demo project example_tin protected from upload overwrite -> 403
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        conn.request("POST", "/api/upload?project=example_tin&name=tin.csv", body=b"X,Y,Z,CU\n0,0,0,1\n", headers={"X-PitOpt": "1"})
        assert conn.getresponse().status == 403
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
