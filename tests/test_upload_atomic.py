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
