from afm_copilot.bootstrap import test_environment as isolated_env


def test_verification_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('AFM_TEST_CORPUS_ROOT', 'do-not-touch')
    monkeypatch.setenv('AFM_TRAINING_ROOT', 'do-not-touch')
    env = isolated_env(tmp_path)
    assert env['AFM_COPILOT_HOME'] == str(tmp_path / 'installation')
    assert env['HOME'] == env['USERPROFILE'] == str(tmp_path)
    assert env['QT_QPA_PLATFORM'] == 'offscreen'
    assert 'AFM_TEST_CORPUS_ROOT' not in env
    assert 'AFM_TRAINING_ROOT' not in env
