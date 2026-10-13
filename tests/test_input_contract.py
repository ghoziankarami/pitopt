"""Fail closed on unknown material; independent metal-mass answers in native units."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pitopt.config import BlockModelConfig, EconomicsConfig, ProductConfig, ProjectConfig
from pitopt.core.economics import marginal_cutoff_grades, value_blocks
from pitopt.io.blockmodel import load_block_model


@pytest.mark.parametrize('column,value', [('X', np.inf), ('Y', np.nan), ('SG', np.nan), ('SG', np.inf),
                                         ('GRADE', np.nan), ('GRADE', np.inf), ('GRADE', -999), ('VOL', 0), ('VOL', -1)])
def test_invalid_material_is_rejected_without_rewriting_source(tmp_path, column, value):
    path = tmp_path / 'blocks.csv'
    data = {'X': [0.0], 'Y': [0.0], 'Z': [0.0], 'SG': [2.0], 'GRADE': [1.0], 'VOL': [500.0]}
    data[column] = [value]
    pd.DataFrame(data).to_csv(path, index=False)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        load_block_model(BlockModelConfig(str(path), grade_col='GRADE', density_col='SG', volume_col='VOL'))
    assert path.read_bytes() == before


@pytest.mark.parametrize('mapping', ['density_col', 'dx_col', 'volume_col', 'domain_col', 'class_col'])
def test_explicit_mapping_cannot_silently_fall_back(tmp_path, mapping):
    path = tmp_path / 'blocks.csv'
    pd.DataFrame({'X': [0], 'Y': [0], 'Z': [0], 'GRADE': [0]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match='ABSENT'):
        load_block_model(BlockModelConfig(str(path), grade_col='GRADE', **{mapping: 'ABSENT'}))


def test_duplicate_centroids_and_empty_model_are_rejected(tmp_path):
    path = tmp_path / 'blocks.csv'
    data = pd.DataFrame({'X': [0, 0], 'Y': [0, 0], 'Z': [0, 0], 'GRADE': [0, 1]})
    data.to_csv(path, index=False)
    with pytest.raises(ValueError, match='Duplicate'):
        load_block_model(BlockModelConfig(str(path), grade_col='GRADE'))
    data.iloc[:0].to_csv(path, index=False)
    with pytest.raises(ValueError, match='no data'):
        load_block_model(BlockModelConfig(str(path), grade_col='GRADE'))


@pytest.mark.parametrize('basis,grade,density,metal', [('mass_percent', 1.5, 2, 3.0), ('gpt', 2, 2, 0.0004),
                                                    ('ppm', 2, 2, 0.0004), ('kgm3', 0.8, 2, 0.08),
                                                    ('kgm3', 0.8, 4, 0.08), ('gm3', 800, 4, 0.08)])
def test_native_units_match_independent_mass_and_cutoff(basis, grade, density, metal):
    # 100 m3 of rock, recovery 50% then 80%. No dilution metal is invented.
    df = pd.DataFrame({'x': [0], 'y': [0], 'z': [0], 'dx': [10], 'dy': [10], 'dz': [1],
                       'density': [density], 'GRADE': [grade]})
    product = ProductConfig(name='METAL', grade_col='GRADE', price=30000, plant_recovery=0.8)
    econ = EconomicsConfig(grade_basis=basis, mining_recovery=0.5, dilution=0.1,
                           processing_cost_per_volume=1, products=[product])
    result = value_blocks(df, econ)
    assert result.METAL_tonnes.iloc[0] == pytest.approx(metal * 0.5 * 0.8)
    cutoff = marginal_cutoff_grades(econ, rock_density=density)['METAL']
    at_cutoff = value_blocks(df.assign(GRADE=cutoff), econ)
    assert at_cutoff.value_ore.iloc[0] == pytest.approx(at_cutoff.value_waste.iloc[0], abs=1e-9)


def test_ui_grade_options_are_accepted_by_the_engine():
    import re

    root = Path(__file__).resolve().parents[1]
    for name in ['upload.js', 'params.js']:
        text = (root / 'pitopt/ui/static/js/views' / name).read_text()
        choices = re.search(r'\["mass_percent"[^\]]*\]', text).group()
        for basis in re.findall(r'"([a-z0-9_]+)"', choices):
            cfg = ProjectConfig.from_yaml(str(root / 'projects/example_tin/project.yaml'))
            cfg.economics.grade_basis = basis
            cfg.validate()


@pytest.mark.parametrize('path', [('economics', 'mining_cost_per_tonne'), ('schedule', 'ore_capacity')])
def test_nonfinite_parameters_cannot_produce_a_run(path):
    root = Path(__file__).resolve().parents[1]
    cfg = ProjectConfig.from_yaml(str(root / 'projects/example_tin/project.yaml'))
    setattr(getattr(cfg, path[0]), path[1], float('nan'))
    with pytest.raises(ValueError, match='finite'):
        cfg.validate()


def test_category_codes_remain_literal_and_zero_grade_is_valid(tmp_path):
    path = tmp_path / 'blocks.csv'
    path.write_text('X,Y,Z,GRADE,DOMAIN,CLASS\n0,0,0,0,001,002\n')
    got = load_block_model(BlockModelConfig(str(path), grade_col='GRADE', domain_col='DOMAIN', class_col='CLASS'))
    assert got.domain.tolist() == ['001']
    assert got.resource_class.tolist() == ['002']
    assert got.GRADE.tolist() == [0]


def test_category_na_and_null_are_literal_identifiers(tmp_path):
    path = tmp_path / 'blocks.csv'
    path.write_text('X,Y,Z,GRADE,DOMAIN,CLASS\n0,0,0,1,NA,NULL\n10,0,0,2,NULL,NA\n')
    got = load_block_model(BlockModelConfig(str(path), grade_col='GRADE', domain_col='DOMAIN', class_col='CLASS'))
    assert got.domain.tolist() == ['NA', 'NULL']
    assert got.resource_class.tolist() == ['NULL', 'NA']


def test_source_row_identity_survives_clipping_and_does_not_overwrite_a_grade(tmp_path):
    from pitopt.pipeline import clip_to_surface

    path = tmp_path / 'm.csv'
    path.write_text('X,Y,Z,source_row\n0,0,10,6\n10,0,0,7\n')
    loaded = load_block_model(BlockModelConfig(str(path), grade_col='source_row'))
    assert loaded.source_row.tolist() == [6, 7]
    row_field = loaded.attrs['source_row_field']
    assert loaded[row_field].tolist() == [1, 2]
    clipped = clip_to_surface(loaded, lambda x, y: np.zeros(len(x)))
    assert clipped[row_field].tolist() == [2]
