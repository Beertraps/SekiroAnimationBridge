"""Owned socket/bone fixtures; no game files needed."""
import sys,unittest,tempfile
from pathlib import Path
from types import SimpleNamespace as S
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from weapon_assets import (attachment,bone_worlds,dummy_frame,socket_choice,reference_file,weapon_attachment,
                           extra_model_kind,describe_attachment)


def bone(name='Hand',parent=-1,t=(1,2,3),r=(0,0,0)):
    return S(name=name,parent_bone_index=parent,translate=t,rotate=r,scale=(1,1,1))


def dummy(ident=20,**kwargs):
    return S(reference_id=ident,parent_bone_index=-1,attach_bone_index=0,translate=(2,3,4),
             forward=(0,0,-2),upward=(0,5,0),use_upward_vector=True,follows_attach_bone=True,**kwargs)


class WeaponAttachments(unittest.TestCase):
    def test_drawn_sword_and_sheath_are_separate(self):
        self.assertEqual(socket_choice('wp_a_0300',0),20)
        self.assertEqual(socket_choice('wp_a_0300',1),147)
        self.assertEqual(socket_choice('wp_a_0310',0),149)
        self.assertEqual(socket_choice('wp_a_0310',0,'right'),20)
        self.assertEqual(socket_choice('wp_a_0310',1,'right'),149)
    def test_prosthetics_use_their_authored_sockets(self):
        self.assertEqual(socket_choice('wp_a_0700',0),112)
        self.assertEqual(socket_choice('wp_a_0782',0),123)
    def test_unknown_weapon_needs_an_explicit_choice(self):
        with self.assertRaisesRegex(ValueError,'no verified'):socket_choice('wp_a_9998',0)
        self.assertEqual(socket_choice('wp_a_9998',0,'left'),21)
        self.assertEqual(socket_choice('wp_a_9998',0,'dummy:123'),123)
    def test_sekiro_rejects_souls_only_states(self):
        for placement in ('both','sheath-left'):
            with self.assertRaisesRegex(ValueError,'Invalid Sekiro'):socket_choice('wp_a_0300',0,placement)
    def test_souls_auto_uses_param_default_row_for_any_weapon(self):
        for game in ('ds3','er','ds1','ds1r'):
            self.assertEqual(socket_choice('wp_a_0207',0,'auto',game),20)
            # A right-hand weapon's extra model hangs on the left hip.
            self.assertEqual(socket_choice('wp_a_0207',1,'auto',game),30)
            self.assertEqual(socket_choice('wp_a_0207',1,'right',game),30)
            self.assertEqual(socket_choice('wp_a_0207',0,'left',game),21)
            self.assertEqual(socket_choice('wp_a_0207',1,'left',game),31)
            self.assertEqual([socket_choice('wp_a_0207',i,'sheath',game) for i in (0,1)],[30,30])
            self.assertEqual([socket_choice('wp_a_0207',i,'sheath-left',game) for i in (0,1)],[31,31])
    def test_two_handed_keeps_scabbards_on_the_hip(self):
        self.assertEqual(socket_choice('wp_a_0207',0,'both','er'),24)
        self.assertEqual(socket_choice('wp_a_0207',1,'both','er',['WP_A_0207_Sheath']),30)
        self.assertEqual(socket_choice('wp_a_0201',1,'both','ds3',['WP_A_0201_1']),30)
        self.assertEqual(socket_choice('wp_a_0999',1,'both','er',['dymmy','WP_A_0999_1']),21)
        self.assertEqual(socket_choice('wp_a_0999',1,'both','er',[]),30)
    def test_extra_models_are_classified_by_their_bones(self):
        self.assertEqual(extra_model_kind('wp_a_0207',1,'er',['WP_A_0207_Sheath']),'scabbard')
        self.assertEqual(extra_model_kind('wp_a_0201',1,'ds3',['WP_A_0201_1']),'scabbard')
        self.assertEqual(extra_model_kind('wp_a_0999',1,'er',['dymmy']),'paired')
        self.assertEqual(extra_model_kind('wp_a_0999',1,'er',['dummy_throw_sfx']),'accessory')
    def test_custom_dummy_lists_are_per_model(self):
        self.assertEqual([socket_choice('wp_a_0207',i,'dummy:20,30','er') for i in (0,1,2)],[20,30,30])
        self.assertEqual([socket_choice('wp_a_0207',i,'dummy: 33','er') for i in (0,1)],[33,33])
        for bad in ('dummy:','dummy:a','dummy:20,,30','dummy:40000'):
            with self.assertRaisesRegex(ValueError,'Invalid weapon attachment'):socket_choice('wp_a_0207',0,bad,'er')
        with self.assertRaisesRegex(ValueError,'no automatic back'):socket_choice('wp_a_0207',0,'back','er')
    def test_ds1_uses_cross_draw_case_bones(self):
        bones=[bone('Pelvis',t=(0,1,0)),bone('R_Weapon',0,(-0.7,0.4,0)),bone('L_Weapon',0,(0.7,0.4,0)),
               bone('R_Wepon_Case',0,(-0.2,0,0)),bone('L_Wepon_Case',0,(0.2,0,0))]
        reference=S(bones=bones,dummies=[])
        anchor=lambda i,p:weapon_attachment(reference,'wp_a_0201',i,p,'ds1')['anchorBone']
        self.assertEqual([anchor(0,'auto'),anchor(1,'auto')],['R_Weapon','L_Wepon_Case'])
        self.assertEqual([anchor(0,'left'),anchor(1,'left')],['L_Weapon','R_Wepon_Case'])
        self.assertEqual([anchor(0,'sheath'),anchor(0,'sheath-left')],['L_Wepon_Case','R_Wepon_Case'])
    def test_resolved_sockets_are_described_and_model_two_is_flagged(self):
        reference=S(bones=[bone('Pelvis')],dummies=[dummy(30)])
        result=weapon_attachment(reference,'wp_a_0207',2,'auto','er')
        self.assertIn('left hip',describe_attachment(result));self.assertIn('model 2',result['notice'])
        self.assertNotIn('notice',weapon_attachment(reference,'wp_a_0207',1,'auto','er'))
    def test_dummy_axes_are_orthonormal(self):
        matrix=dummy_frame(dummy());np.testing.assert_allclose(matrix[:3,:3],np.eye(3))
        np.testing.assert_allclose(matrix[:3,3],[2,3,4])
    def test_offset_is_relative_to_attach_bone_bind_pose(self):
        reference=S(bones=[bone()],dummies=[dummy()]);a=attachment(reference,20)
        self.assertEqual(a['bone'],'Hand')
        # Convert game xyz -> Blender xzy and account for weapon Y half-turn.
        np.testing.assert_allclose(np.asarray(a['matrix'])[:3,3],[1,1,1])
        np.testing.assert_allclose(np.asarray(a['matrix'])[:3,:3],np.diag([-1,-1,1]))
    def test_parent_and_attach_bones_are_not_interchangeable(self):
        reference=S(bones=[bone('Hand'),bone('Reference',t=(0,1,0))],dummies=[dummy()])
        reference.dummies[0].parent_bone_index=1
        a=attachment(reference,20);np.testing.assert_allclose(np.asarray(a['matrix'])[:3,3],[1,1,2])
    def test_missing_and_ambiguous_dummies_are_explained(self):
        for dummies in ([],[dummy(),dummy()]):
            with self.assertRaisesRegex(ValueError,'matches'):attachment(S(bones=[bone()],dummies=dummies),20)
    def test_zero_direction_and_bone_cycles_are_rejected(self):
        d=dummy();d.forward=(0,0,0)
        with self.assertRaisesRegex(ValueError,'direction vector'):dummy_frame(d)
        with self.assertRaisesRegex(ValueError,'cycle'):bone_worlds([bone(parent=0)])
    def test_reference_is_required_and_finds_an_existing_binder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'wp_a_0300.partsbnd.dcx';source.touch()
            with self.assertRaisesRegex(ValueError,'c0000.chrbnd'):reference_file([source])
            reference=root/'c0000.chrbnd.dcx';reference.write_bytes(b'owned reference fixture')
            self.assertEqual(reference_file([source]),reference)


if __name__=='__main__':unittest.main()
