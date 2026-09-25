"""
Tests for the transitions state machine library.

Each test exercises a meaningful end-user pattern, typically combining
multiple features (nesting + callbacks, locking + context, markup + hierarchy, etc.).
"""

import asyncio
import pickle
import threading
import time
from enum import Enum
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Core Machine integration tests
# ---------------------------------------------------------------------------


class TestCoreIntegration:
    """Integration tests combining core Machine features."""

    def test_full_workflow_with_callbacks_conditions_queued(self):
        """A user builds a multi-step workflow with callbacks, conditions, queued transitions, and state checks."""
        from transitions import Machine, State

        log = []

        class Workflow:
            approved = False

            def check_approval(self):
                return self.approved

            def on_enter_reviewing(self):
                log.append('enter_reviewing')

            def on_exit_reviewing(self):
                log.append('exit_reviewing')

            def notify(self):
                log.append('notified')

            def record(self):
                log.append('recorded')

        model = Workflow()
        machine = Machine(
            model=model,
            states=['draft', 'reviewing', 'approved', 'rejected',
                    State('published', final=True)],
            initial='draft',
            queued=True,
            on_final=lambda: log.append('final_reached'),
            auto_transitions=False,
        )
        machine.add_transition('submit', 'draft', 'reviewing', after='notify')
        machine.add_transition('approve', 'reviewing', 'approved',
                               conditions='check_approval', after='record')
        machine.add_transition('approve', 'reviewing', 'rejected',
                               unless='check_approval')
        machine.add_transition('publish', 'approved', 'published')

        # Submit draft
        model.submit()
        assert model.state == 'reviewing'
        assert 'enter_reviewing' in log
        assert 'notified' in log

        # Try approve without approval flag — should reject
        model.approve()
        assert model.state == 'rejected'
        assert 'exit_reviewing' in log

        # Reset and approve properly
        model2 = Workflow()
        model2.approved = True
        machine.add_model(model2, initial='reviewing')
        model2.approve()
        assert model2.state == 'approved'
        assert 'recorded' in log

        model2.publish()
        assert model2.state == 'published'
        assert 'final_reached' in log

    def test_callback_execution_order_complete(self):
        """A user verifies the complete callback execution order including on_final placement."""
        from transitions import Machine, State

        log = []

        class Model:
            def global_prepare(self):
                log.append('global_prepare')
            def trans_prepare(self):
                log.append('trans_prepare')
            def trans_condition(self):
                log.append('trans_condition')
                return True
            def global_before(self):
                log.append('global_before')
            def trans_before(self):
                log.append('trans_before')
            def on_exit_A(self):
                log.append('exit_A')
            def on_enter_B(self):
                log.append('enter_B')
            def on_final_cb(self):
                log.append('on_final')
            def trans_after(self):
                log.append('trans_after')
            def global_after(self):
                log.append('global_after')
            def global_finalize(self):
                log.append('global_finalize')

        model = Model()
        Machine(
            model=model, states=['A', State('B', final=True)], initial='A',
            transitions=[{
                'trigger': 'go', 'source': 'A', 'dest': 'B',
                'prepare': 'trans_prepare',
                'conditions': 'trans_condition',
                'before': 'trans_before',
                'after': 'trans_after',
            }],
            prepare_event='global_prepare',
            before_state_change='global_before',
            after_state_change='global_after',
            finalize_event='global_finalize',
            on_final='on_final_cb',
            auto_transitions=False,
        )
        model.go()
        assert log == [
            'global_prepare', 'trans_prepare', 'trans_condition',
            'global_before', 'trans_before', 'exit_A', 'enter_B',
            'on_final', 'trans_after', 'global_after', 'global_finalize'
        ]

    def test_exception_handling_and_event_data(self):
        """A user uses on_exception, finalize_event, and send_event with arguments together."""
        from transitions import Machine

        errors = []
        finalized = []
        received = {}

        def bad_callback(event_data):
            raise ValueError("boom")

        class Model:
            def handle_error(self, event_data):
                errors.append(event_data.error)
            def finalize(self, event_data):
                finalized.append(event_data.event.name)

        model = Model()
        Machine(model=model, states=['A', 'B', 'C'], initial='A',
                transitions=[
                    {'trigger': 'fail', 'source': 'A', 'dest': 'B', 'before': bad_callback},
                ],
                on_exception='handle_error', finalize_event='finalize',
                send_event=True, auto_transitions=False)
        model.fail()
        assert len(errors) == 1
        assert str(errors[0]) == 'boom'
        assert model.state == 'A'
        assert 'fail' in finalized  # finalize runs even on exception

        # send_event passes EventData to callbacks with args/kwargs
        def capture(event_data):
            received['event_name'] = event_data.event.name
            received['args'] = event_data.args
            received['kwargs'] = event_data.kwargs
            received['model'] = event_data.model
            received['machine'] = event_data.machine

        m2 = Machine(states=['X', 'Y'], initial='X', send_event=True, auto_transitions=False)
        m2.add_transition('go', 'X', 'Y', after=capture)
        m2.go(42, key='value')
        assert received['event_name'] == 'go'
        assert received['args'] == (42,)
        assert received['kwargs'] == {'key': 'value'}
        assert received['model'] is m2
        assert received['machine'] is m2

        # Async on_exception also preserves state
        async def async_test():
            from transitions.extensions.asyncio import AsyncMachine
            async_errors = []
            async def async_bad(event_data):
                raise ValueError("async_boom")
            class AsyncModel:
                async def handle(self, event_data):
                    async_errors.append(str(event_data.error))
            amodel = AsyncModel()
            am = AsyncMachine(model=amodel, states=['P', 'Q'], initial='P',
                              transitions=[{'trigger': 'go', 'source': 'P', 'dest': 'Q',
                                            'before': async_bad}],
                              on_exception='handle', send_event=True, auto_transitions=False)
            await amodel.go()
            assert async_errors == ['async_boom']
            assert amodel.state == 'P'
        asyncio.run(async_test())

    def test_wildcard_reflexive_internal_and_ordered_transitions(self):
        """A user combines wildcard, reflexive, internal, and ordered transitions."""
        from transitions import Machine, MachineError

        log = []
        m = Machine(states=['A', 'B', 'C', 'D'], initial='A', auto_transitions=False)
        m.add_transition('go', 'A', 'B')
        m.add_transition('advance', 'B', 'C')
        m.add_transition('reset', '*', 'A')
        m.add_transition('touch', '*', '=', after=lambda: log.append('touched'))
        m.add_transition('check', 'A', None, after=lambda: log.append('checked'))

        # Internal transition — no state change, no enter/exit
        m.check()
        assert m.state == 'A'
        assert 'checked' in log

        # Normal + reflexive + wildcard
        m.go()
        assert m.state == 'B'
        m.touch()
        assert m.state == 'B'
        assert 'touched' in log
        m.advance()
        m.reset()
        assert m.state == 'A'

        # Ordered transitions with end-of-chain error
        m2 = Machine(states=['X', 'Y', 'Z'], initial='X', auto_transitions=False)
        m2.add_ordered_transitions(loop=False)
        m2.next_state()
        assert m2.state == 'Y'
        m2.next_state()
        assert m2.state == 'Z'
        with pytest.raises(MachineError):
            m2.next_state()

        # Ordered with loop=True and conditions
        class Model:
            count = 0
            def can_advance(self):
                self.count += 1
                return self.count <= 2

        model = Model()
        m3 = Machine(model=model, states=['P', 'Q', 'R'], initial='P', auto_transitions=False)
        m3.add_ordered_transitions(loop=True, conditions='can_advance')
        model.next_state()
        model.next_state()
        assert model.state == 'R'
        result = model.next_state()  # condition fails
        assert result is False
        assert model.state == 'R'

    def test_multiple_models_and_dispatch(self):
        """A user manages multiple models with independent state and uses dispatch."""
        from transitions import Machine

        class Obj:
            pass
        m1, m2, m3 = Obj(), Obj(), Obj()
        machine = Machine(model=[m1, m2, m3], states=['A', 'B', 'C'],
                          transitions=[['go', 'A', 'B'], ['advance', 'B', 'C']],
                          initial='A', ignore_invalid_triggers=True, auto_transitions=False)

        # Independent state
        m1.go()
        assert m1.state == 'B'
        assert m2.state == 'A'

        # Dispatch triggers on all models
        machine.dispatch('go')
        assert m1.state == 'B'  # already in B, go not valid from B
        assert m2.state == 'B'
        assert m3.state == 'B'

        machine.dispatch('advance')
        assert m1.state == 'C'
        assert m2.state == 'C'
        assert m3.state == 'C'

    def test_dynamic_lifecycle_and_multiple_machines(self):
        """A user dynamically manages models/transitions and attaches one model to two machines."""
        from transitions import Machine

        class Obj:
            pass

        # Dynamic add/remove
        machine = Machine(model=None, states=['A', 'B'], initial='A', auto_transitions=False)
        machine.add_state('C')
        machine.add_transition('go', 'A', 'B')
        machine.add_transition('go', 'B', 'C')
        machine.add_transition('back', 'C', 'A')
        obj = Obj()
        machine.add_model(obj)
        obj.go()
        obj.go()
        assert obj.state == 'C'
        machine.remove_transition('go', source='A', dest='B')
        remaining = machine.get_transitions(trigger='go')
        assert len(remaining) == 1
        assert remaining[0].source == 'B' and remaining[0].dest == 'C'
        machine.remove_model(obj)
        assert obj not in machine.models

        # One model, two machines with different model_attributes
        model = Obj()
        m1 = Machine(model=model, states=['idle', 'active'],
                     transitions=[['activate', 'idle', 'active']],
                     initial='idle', auto_transitions=False)
        m2 = Machine(model=model, states=['off', 'on'],
                     transitions=[['turn_on', 'off', 'on']],
                     initial='off', model_attribute='power', auto_transitions=False)
        assert model.state == 'idle'
        assert model.power == 'off'
        model.activate()
        model.turn_on()
        assert model.state == 'active'
        assert model.power == 'on'

        # Trigger name collision with model_attribute raises ValueError
        with pytest.raises(ValueError):
            Machine(states=['X', 'Y'], initial='X',
                    transitions=[['state', 'X', 'Y']])

    def test_enum_states_full_workflow(self):
        """A user uses Enum states with transitions, conditions, and state checks."""
        from transitions import Machine

        class Light(Enum):
            RED = 1
            YELLOW = 2
            GREEN = 3

        class Controller:
            can_proceed = True
            def check(self):
                return self.can_proceed

        ctrl = Controller()
        Machine(model=ctrl, states=Light, initial=Light.RED, auto_transitions=False,
                transitions=[
                    {'trigger': 'next', 'source': Light.RED, 'dest': Light.GREEN,
                     'conditions': 'check'},
                    ['next', Light.GREEN, Light.YELLOW],
                    ['next', Light.YELLOW, Light.RED],
                ])

        ctrl.next()
        assert ctrl.state == Light.GREEN
        ctrl.next()
        assert ctrl.state == Light.YELLOW
        ctrl.next()
        assert ctrl.state == Light.RED

        ctrl.can_proceed = False
        result = ctrl.may_next()
        assert result is False

    def test_model_attribute_customization(self):
        """A user customizes the state attribute name and uses is_<attr>_<state>() and to_<attr>_<state>()."""
        from transitions import Machine

        m = Machine(states=['active', 'inactive', 'suspended'], initial='active',
                    model_attribute='status')
        assert m.status == 'active'
        assert m.is_status_active()
        assert not m.is_status_inactive()
        m.to_status_suspended()
        assert m.status == 'suspended'
        assert m.is_status_suspended()

    def test_queued_chains_and_error_handling(self):
        """A user uses queued mode for callback-triggered chains and verifies error handling."""
        from transitions import Machine

        # Chain: A→B→C→D via queued callbacks
        class Model:
            pass
        model = Model()
        machine = Machine(model=model, states=['A', 'B', 'C', 'D'], initial='A',
                          queued=True, auto_transitions=False)

        def chain_to_c():
            model.to_c()
        def chain_to_d():
            model.to_d()

        machine.add_transition('to_b', 'A', 'B', after=chain_to_c)
        machine.add_transition('to_c', 'B', 'C', after=chain_to_d)
        machine.add_transition('to_d', 'C', 'D')
        model.to_b()
        assert model.state == 'D'

        # Error handling in queued mode
        log = []
        class Model2:
            def explode(self, event_data):
                raise ValueError("queued_boom")
            def handle_error(self, event_data):
                log.append(f"caught:{event_data.error}")
            def finalize(self, event_data):
                log.append("finalized")

        model2 = Model2()
        m2 = Machine(model=model2, states=['X', 'Y'], initial='X', queued=True,
                     on_exception='handle_error', finalize_event='finalize',
                     send_event=True, auto_transitions=False)
        m2.add_transition('go', 'X', 'Y', before='explode')
        model2.go()
        assert model2.state == 'X'
        assert any('queued_boom' in entry for entry in log)
        assert 'finalized' in log

    def test_conditions_introspection_and_set_state(self):
        """A user uses conditions for routing, introspects transitions/triggers, and uses set_state."""
        from transitions import Machine

        class Model:
            priority = 0
            def is_high(self):
                return self.priority > 5
            def is_low(self):
                return self.priority <= 5

        model = Model()
        model.priority = 3
        machine = Machine(model=model, states=['idle', 'fast', 'slow'], initial='idle',
                          transitions=[
                              {'trigger': 'process', 'source': 'idle', 'dest': 'fast',
                               'conditions': 'is_high'},
                              {'trigger': 'process', 'source': 'idle', 'dest': 'slow',
                               'conditions': 'is_low'},
                              {'trigger': 'go', 'source': 'idle', 'dest': 'fast'},
                              {'trigger': 'go', 'source': 'fast', 'dest': 'slow'},
                          ], auto_transitions=False)
        model.process()
        assert model.state == 'slow'

        # Introspection
        all_go = machine.get_transitions(trigger='go')
        assert len(all_go) == 2
        from_idle = machine.get_transitions(trigger='go', source='idle')
        assert len(from_idle) == 1 and from_idle[0].dest == 'fast'
        triggers = machine.get_triggers('idle')
        assert 'process' in triggers
        assert 'go' in triggers

        # set_state bypasses callbacks
        log = []
        machine.get_state('idle').on_enter.append(lambda: log.append('enter_idle'))
        machine.set_state('idle', model=model)
        assert model.state == 'idle'
        assert log == []  # no callbacks triggered

        # Dynamic state addition from on_enter callback
        add_log = []
        m3 = Machine(states=['P', 'Q'], initial='P', auto_transitions=True)
        m3.get_state('Q').on_enter.append(lambda: (m3.add_state('R'), add_log.append('added_R')))
        m3.to_Q()
        assert 'added_R' in add_log
        m3.to_R()
        assert m3.state == 'R'


# ---------------------------------------------------------------------------
# Hierarchical Machine integration tests
# ---------------------------------------------------------------------------


class TestHierarchicalIntegration:
    """Integration tests for HierarchicalMachine with nesting, callbacks, transitions."""

    def test_deeply_nested_with_callbacks_and_parent_transitions(self):
        """A user creates deeply nested states, attaches callbacks, and transitions from parent to child."""
        from transitions.extensions.nesting import HierarchicalMachine

        log = []

        class Model:
            def on_enter_B_2_a(self):
                log.append('enter_B_2_a')
            def on_exit_B_2_a(self):
                log.append('exit_B_2_a')
            def on_enter_B_2_b(self):
                log.append('enter_B_2_b')

        model = Model()
        states = [
            'A',
            {'name': 'B', 'children': [
                '1',
                {'name': '2', 'children': ['a', 'b']},
            ]},
            'C'
        ]
        machine = HierarchicalMachine(
            model=model, states=states, initial='A', auto_transitions=False)
        machine.add_transition('go', 'A', 'B_2_a')
        machine.add_transition('advance', 'B_2_a', 'B_2_b')
        machine.add_transition('reset', 'B', 'C')  # parent-level: applies to all children

        model.go()
        assert model.state == 'B_2_a'
        assert 'enter_B_2_a' in log
        assert model.is_B(allow_substates=True)

        model.advance()
        assert model.state == 'B_2_b'
        assert 'exit_B_2_a' in log
        assert 'enter_B_2_b' in log

        model.reset()
        assert model.state == 'C'

    def test_nesting_basics_separator_and_auto_transitions(self):
        """A user tests initial substate entry, custom separator, and nested auto-transitions."""
        from transitions.extensions.nesting import HierarchicalMachine, NestedState

        # Initial substate auto-entry
        states = ['A', {'name': 'B', 'initial': '2', 'children': ['1', '2', '3']}]
        m = HierarchicalMachine(states=states, initial='A', auto_transitions=True)
        m.add_transition('go', 'A', 'B')
        m.go()
        assert m.state == 'B_2'

        # Auto-transitions with nested states
        m.to_B_1()
        assert m.state == 'B_1'
        m.to_A()
        assert m.state == 'A'
        m.to_B()
        assert m.state == 'B_2'  # enters initial child

        # Custom separator
        old_sep = NestedState.separator
        try:
            NestedState.separator = '.'
            states2 = ['X', {'name': 'Y', 'children': ['a', 'b']}]
            m2 = HierarchicalMachine(states=states2, initial='X', auto_transitions=False)
            m2.add_transition('go', 'X', 'Y.a')
            m2.add_transition('switch', 'Y.a', 'Y.b')
            m2.go()
            assert m2.state == 'Y.a'
            m2.switch()
            assert m2.state == 'Y.b'
        finally:
            NestedState.separator = old_sep

    def test_nested_state_programmatic_construction(self):
        """A user builds nested states programmatically with NestedState objects and add_substate."""
        from transitions.extensions.nesting import HierarchicalMachine, NestedState

        a = NestedState('A')
        b = NestedState('B')
        b1 = NestedState('1')
        b2 = NestedState('2')
        b.add_substate(b1)
        b.add_substates([b2])
        m = HierarchicalMachine(states=[a, b], initial='A', auto_transitions=False)
        m.add_transition('go', 'A', 'B_1')
        m.add_transition('advance', 'B_1', 'B_2')
        m.go()
        assert m.state == 'B_1'
        m.advance()
        assert m.state == 'B_2'

    def test_parallel_states(self):
        """A user defines parallel (concurrent) substates that are entered simultaneously."""
        from transitions.extensions.nesting import HierarchicalMachine

        states = ['A', {'name': 'P',
                        'parallel': [
                            {'name': '1', 'children': ['a', 'b'], 'initial': 'a',
                             'transitions': [['go', 'a', 'b']]},
                            {'name': '2', 'children': ['a', 'b'], 'initial': 'a',
                             'transitions': [['go', 'a', 'b']]}
                        ]}]
        transitions = [['reset', 'P', 'A']]
        m = HierarchicalMachine(states=states, transitions=transitions, initial='A',
                                auto_transitions=False)
        m.add_transition('enter_p', 'A', 'P')
        m.enter_p()
        # Should be in both parallel substates
        assert isinstance(m.state, list)
        assert 'P_1_a' in m.state
        assert 'P_2_a' in m.state

        # Trigger transition inside parallel states
        m.go()
        assert 'P_1_b' in m.state
        assert 'P_2_b' in m.state

        m.reset()
        assert m.state == 'A'

    def test_blueprint_reuse_and_queued_remap(self):
        """A user embeds a machine as children with remap, and combines remap with queued mode."""
        from transitions.extensions.nesting import HierarchicalMachine

        # Blueprint reuse with remap
        counter_states = ['1', '2', '3', 'finished']
        counter_transitions = [
            ['increase', '1', '2'],
            ['increase', '2', '3'],
            ['decrease', '3', '2'],
            ['decrease', '2', '1'],
            ['reset', '*', '1'],
            ['done', '3', 'finished'],
        ]
        counter = HierarchicalMachine(states=counter_states,
                                       transitions=counter_transitions, initial='1')

        new_states = ['A', 'B', {'name': 'C', 'children': counter,
                                  'remap': {'finished': 'A'}}]
        new_transitions = [
            ['forward', 'A', 'B'],
            ['forward', 'B', 'C_1'],
        ]
        walker = HierarchicalMachine(states=new_states, transitions=new_transitions, initial='A')
        walker.forward()
        assert walker.state == 'B'
        walker.forward()
        assert walker.state == 'C_1'
        walker.increase()
        walker.increase()
        assert walker.state == 'C_3'
        walker.done()
        assert walker.state == 'A'  # remap: finished → A

        # Queued mode with remap
        log = []
        sub_states2 = ['1', '2', 'finished']
        sub_transitions2 = [['step', '1', '2'], ['done', '2', 'finished']]
        sub_machine = HierarchicalMachine(states=sub_states2,
                                            transitions=sub_transitions2, initial='1')
        states2 = ['idle', {'name': 'working', 'children': sub_machine,
                             'remap': {'finished': 'idle'}}]
        m2 = HierarchicalMachine(states=states2, initial='idle', queued=True,
                                  auto_transitions=False,
                                  after_state_change=lambda: log.append(m2.state))
        m2.add_transition('start', 'idle', 'working_1')
        m2.start()
        m2.step()
        m2.done()
        assert m2.state == 'idle'
        assert 'idle' in log

        # Multi-level remap cascade (3 levels deep)
        inner = HierarchicalMachine(states=['start', 'done'],
                                     transitions=[['finish', 'start', 'done']], initial='start')
        middle_s = ['begin', {'name': 'work', 'children': inner,
                              'remap': {'done': 'complete'}}, 'complete']
        middle = HierarchicalMachine(states=middle_s,
                                      transitions=[['start_work', 'begin', 'work_start']], initial='begin')
        outer_s = ['idle', {'name': 'active', 'children': middle,
                            'remap': {'complete': 'idle'}}]
        m3 = HierarchicalMachine(states=outer_s,
                                  transitions=[['activate', 'idle', 'active_begin']], initial='idle')
        m3.activate()
        m3.start_work()
        assert m3.state == 'active_work_start'
        m3.finish()
        assert m3.state == 'idle'  # cascaded through 2 remap levels

    def test_parallel_state_exit_callbacks(self):
        """A user attaches exit callbacks to parallel states and verifies they fire correctly."""
        from transitions.extensions.nesting import HierarchicalMachine

        mock = MagicMock()

        class Model:
            def on_exit_P(self):
                mock()
            def on_exit_P_1(self):
                mock()
            def on_exit_P_2(self):
                mock()

        model = Model()
        states = ['A', {'name': 'P', 'parallel': ['1', '2']}]
        m = HierarchicalMachine(model=model, states=states,
                                transitions=[['reset', 'P', 'A']], initial='A')
        model.to_P()
        assert isinstance(model.state, list)
        model.reset()
        assert model.is_A()
        # on_exit should fire for P, P_1, P_2
        assert mock.call_count == 3


# ---------------------------------------------------------------------------
# Markup Machine integration tests
# ---------------------------------------------------------------------------


class TestMarkupIntegration:
    """Integration tests for MarkupMachine serialization/deserialization."""

    def test_markup_round_trip_with_conditions_callbacks(self):
        """A user serializes a machine with conditions and callbacks, then recreates and runs it."""
        from transitions.extensions.markup import MarkupMachine

        states = ['idle', 'processing', 'done']
        transitions = [
            {'trigger': 'start', 'source': 'idle', 'dest': 'processing'},
            {'trigger': 'finish', 'source': 'processing', 'dest': 'done'},
        ]
        m1 = MarkupMachine(states=states, transitions=transitions, initial='idle',
                            auto_transitions=False, name='TestMachine')
        markup = m1.markup

        m2 = MarkupMachine(markup=markup)
        assert m2.state == 'idle'
        m2.start()
        assert m2.state == 'processing'
        m2.finish()
        assert m2.state == 'done'

        # Verify markup structure precisely
        state_names = [s['name'] for s in markup['states']]
        assert state_names == ['idle', 'processing', 'done']
        assert markup['initial'] == 'idle'
        assert markup['name'] == 'TestMachine'
        assert markup['model_attribute'] == 'state'

        # Verify transitions in markup
        start_trans = [t for t in markup['transitions'] if t['trigger'] == 'start'][0]
        assert start_trans['source'] == 'idle'
        assert start_trans['dest'] == 'processing'

        finish_trans = [t for t in markup['transitions'] if t['trigger'] == 'finish'][0]
        assert finish_trans['source'] == 'processing'
        assert finish_trans['dest'] == 'done'

        # auto_transitions_markup control
        m3 = MarkupMachine(states=['A', 'B'], initial='A', auto_transitions=True,
                           auto_transitions_markup=False)
        trigger_names = [t['trigger'] for t in m3.markup['transitions']]
        assert 'to_A' not in trigger_names
        assert 'to_B' not in trigger_names

        m4 = MarkupMachine(states=['A', 'B'], initial='A', auto_transitions=True,
                           auto_transitions_markup=True)
        trigger_names2 = [t['trigger'] for t in m4.markup['transitions']]
        assert 'to_A' in trigger_names2
        assert 'to_B' in trigger_names2

    def test_hierarchical_markup_round_trip(self):
        """A user serializes/deserializes a hierarchical machine and runs transitions."""
        from transitions.extensions.markup import HierarchicalMarkupMachine

        states = ['A', {'name': 'B', 'children': [
            {'name': '1'},
            {'name': '2', 'children': ['x', 'y']}
        ]}]
        transitions = [
            {'trigger': 'go', 'source': 'A', 'dest': 'B_1'},
            {'trigger': 'dive', 'source': 'B_1', 'dest': 'B_2_x'},
            {'trigger': 'switch', 'source': 'B_2_x', 'dest': 'B_2_y'},
        ]
        m1 = HierarchicalMarkupMachine(states=states, transitions=transitions,
                                         initial='A', auto_transitions=False)
        markup = m1.markup

        m2 = HierarchicalMarkupMachine(markup=markup)
        m2.go()
        assert m2.state == 'B_1'
        m2.dive()
        assert m2.state == 'B_2_x'
        m2.switch()
        assert m2.state == 'B_2_y'

        # Markup preserves state callbacks
        m3 = HierarchicalMarkupMachine(
            states=[{'name': 'A', 'on_enter': 'log_enter'}, 'B'],
            transitions=[['go', 'A', 'B']], initial='A', auto_transitions=False)
        markup3 = m3.markup
        a_state = [s for s in markup3['states'] if s['name'] == 'A'][0]
        assert 'on_enter' in a_state
        assert 'log_enter' in a_state['on_enter']

    def test_nested_markup_with_definitions_inside_states(self):
        """A user defines transitions and initial state inside a nested state dict and serializes."""
        from transitions.extensions.markup import HierarchicalMarkupMachine

        states = [
            {'name': 'A'},
            {'name': 'B'},
            {'name': 'C',
             'children': [
                 {'name': '1'},
                 {'name': '2'}],
             'transitions': [
                 {'trigger': 'go', 'source': '1', 'dest': '2'}],
             'initial': '2'}
        ]
        m = HierarchicalMarkupMachine(states=states, initial='A', auto_transitions=False,
                                       name='TestMachine')
        markup = m.markup

        assert markup['initial'] == 'A'
        assert markup['name'] == 'TestMachine'

        # Verify nested state structure is preserved in markup
        state_names_top = [s['name'] for s in markup['states']]
        assert 'A' in state_names_top
        assert 'C' in state_names_top

        c_state = [s for s in markup['states'] if s['name'] == 'C'][0]
        assert 'children' in c_state
        child_names = [ch['name'] for ch in c_state['children']]
        assert '1' in child_names
        assert '2' in child_names

        # Verify nested transitions are preserved in markup
        c_state_transitions = c_state.get('transitions', [])
        assert len(c_state_transitions) == 1
        assert c_state_transitions[0]['trigger'] == 'go'
        assert c_state_transitions[0]['source'] == '1'
        assert c_state_transitions[0]['dest'] == '2'

        # Verify initial is preserved
        assert c_state.get('initial') == '2'



# ---------------------------------------------------------------------------
# LockedMachine integration tests
# ---------------------------------------------------------------------------


class TestLockedIntegration:
    """Integration tests for LockedMachine thread safety."""

    def test_locked_machine_thread_safety_and_context(self):
        """A user uses LockedMachine with threads, lock serialization, and custom context managers."""
        from transitions.extensions.locking import LockedMachine

        # Concurrent triggers — no corruption
        m = LockedMachine(states=['A', 'B'], initial='A',
                          ignore_invalid_triggers=True, auto_transitions=False)
        m.add_transition('toggle_ab', 'A', 'B')
        m.add_transition('toggle_ba', 'B', 'A')
        errors = []

        def trigger_many(n=200):
            try:
                for _ in range(n):
                    if m.state == 'A':
                        m.toggle_ab()
                    else:
                        m.toggle_ba()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=trigger_many) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0
        assert m.state in ('A', 'B')

        # Lock serialization with slow callback
        m2 = LockedMachine(states=['X', 'Y', 'Z'], initial='X')
        def slow_callback():
            time.sleep(1)
        m2.add_transition('forward', 'X', 'Y', before=slow_callback)
        thread = threading.Thread(target=m2.forward)
        thread.start()
        time.sleep(0.05)
        begin = time.time()
        m2.to_Z()
        elapsed = time.time() - begin
        thread.join()
        assert elapsed >= 0.5
        assert m2.state == 'Z'

        # Custom context manager
        class CounterContext:
            def __init__(self):
                self.counter = 0
            def __enter__(self):
                self.counter += 1
            def __exit__(self, *exc):
                pass

        ctx = CounterContext()
        m3 = LockedMachine(states=['P', 'Q'], initial='P',
                           transitions=[['go', 'P', 'Q']],
                           machine_context=ctx, auto_transitions=False)
        m3.go()
        assert m3.state == 'Q'
        assert ctx.counter >= 1

        # Locked + queued interaction — queued chains work under locking
        class QModel:
            pass
        qmodel = QModel()
        m4 = LockedMachine(model=qmodel, states=['W', 'X', 'Y'], initial='W',
                           queued=True, auto_transitions=False)
        def chain_to_y():
            qmodel.to_y()
        m4.add_transition('to_x', 'W', 'X', after=chain_to_y)
        m4.add_transition('to_y', 'X', 'Y')
        qmodel.to_x()
        assert qmodel.state == 'Y'

    def test_locked_hierarchical_machine_with_concurrent_access(self):
        """A user uses LockedHierarchicalMachine from factory with concurrent nested transitions."""
        from transitions.extensions.factory import MachineFactory

        cls = MachineFactory.get_predefined(nested=True, locked=True)
        states = ['idle', {'name': 'active', 'children': ['step1', 'step2'], 'initial': 'step1'}]
        m = cls(states=states, initial='idle', auto_transitions=False,
                ignore_invalid_triggers=True)
        m.add_transition('start', 'idle', 'active')
        m.add_transition('advance', 'active_step1', 'active_step2')
        m.add_transition('finish', 'active', 'idle')

        m.start()
        assert m.state == 'active_step1'
        assert m.is_active(allow_substates=True)
        m.advance()
        assert m.state == 'active_step2'

        errors = []

        def toggle_many(n=100):
            try:
                for _ in range(n):
                    m.finish()
                    m.start()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=toggle_many) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0
        assert m.state in ('idle', 'active_step1')


# ---------------------------------------------------------------------------
# MachineFactory integration
# ---------------------------------------------------------------------------


class TestFactoryIntegration:
    """Tests composing machines via MachineFactory."""

    def test_factory_predefined_combinations(self):
        """A user gets machines with different feature combinations from the factory."""
        from transitions.extensions.factory import MachineFactory

        # nested + locked
        cls_nl = MachineFactory.get_predefined(nested=True, locked=True)
        m1 = cls_nl(states=['A', {'name': 'B', 'children': ['1', '2'], 'initial': '1'}],
                    initial='A', auto_transitions=False)
        m1.add_transition('go', 'A', 'B')
        m1.go()
        assert m1.state == 'B_1'

        # nested only
        cls_n = MachineFactory.get_predefined(nested=True, locked=False)
        m2 = cls_n(states=['X', {'name': 'Y', 'children': ['a', 'b']}],
                   initial='X', auto_transitions=False)
        m2.add_transition('go', 'X', 'Y_a')
        m2.go()
        assert m2.state == 'Y_a'

        # locked only
        cls_l = MachineFactory.get_predefined(nested=False, locked=True)
        m3 = cls_l(states=['P', 'Q'], initial='P', auto_transitions=False)
        m3.add_transition('go', 'P', 'Q')
        m3.go()
        assert m3.state == 'Q'

        # graph + nested
        cls_gn = MachineFactory.get_predefined(graph=True, nested=True)
        m4 = cls_gn(states=['X', {'name': 'Y', 'children': ['a', 'b'], 'initial': 'a'}],
                     initial='X', auto_transitions=False,
                     transitions=[['enter', 'X', 'Y']])
        m4.enter()
        assert m4.state == 'Y_a'
        g = m4.get_graph()
        assert 'enter' in g.source
        assert 'subgraph' in g.source.lower() or 'cluster' in g.source.lower()


# ---------------------------------------------------------------------------
# State Features (Tags, Timeout, Volatile, Retry, Error) integration tests
# ---------------------------------------------------------------------------


class TestStateFeaturesIntegration:
    """Integration tests for state feature mix-ins."""

    def test_state_features_tags_volatile_timeout_retry(self):
        """A user combines Tags, Volatile, Timeout, and Retry state features."""
        from transitions import Machine
        from transitions.extensions.states import add_state_features, Tags, Volatile, Timeout, Retry

        mock = MagicMock()

        @add_state_features(Tags, Volatile, Timeout, Retry)
        class CustomMachine(Machine):
            pass

        states = [
            'idle',
            {'name': 'working', 'tags': ['active', 'important'], 'volatile': dict},
            {'name': 'done', 'tags': ['final']},
            {'name': 'waiting', 'timeout': 0.1, 'on_timeout': ['to_idle']},
            {'name': 'cooling', 'timeout': 0.3, 'on_timeout': mock},
            {'name': 'retrying', 'retries': 2, 'on_failure': 'to_idle'},
        ]
        m = CustomMachine(states=states, initial='idle', auto_transitions=True,
                          transitions=[['start', 'idle', 'working'],
                                       ['finish', 'working', 'done'],
                                       ['restart', 'done', 'working'],
                                       ['retry', 'retrying', 'retrying']])

        # Tags + Volatile
        m.start()
        assert m.get_state('working').is_active
        assert m.get_state('working').is_important
        assert isinstance(m.scope, dict)
        m.scope['progress'] = 50
        m.finish()
        assert m.get_state('done').is_final
        m.restart()
        assert m.scope == {}  # fresh volatile scope

        # Timeout fires
        m.to_waiting()
        assert m.state == 'waiting'
        time.sleep(0.3)
        assert m.state == 'idle'

        # Timeout cancelled on early exit
        m.to_cooling()
        m.to_idle()
        time.sleep(0.5)
        assert not mock.called

        # Retry exhaustion
        m.to_retrying()
        m.retry()
        m.retry()
        m.retry()  # exceeds retries
        assert m.state == 'idle'

    def test_error_state_feature(self):
        """A user uses the Error state feature to reject transitions to non-accepted states."""
        from transitions import Machine, MachineError
        from transitions.extensions.states import add_state_features, Error

        @add_state_features(Error)
        class CustomMachine(Machine):
            pass

        states = ['A', 'B',
                  {'name': 'success', 'accepted': True},
                  {'name': 'failure', 'tags': ['accepted']},
                  'error_state']

        m = CustomMachine(states=states, initial='A', auto_transitions=False,
                          transitions=[
                              ['go', 'A', 'B'],
                              ['succeed', 'B', 'success'],
                              ['fail_accepted', 'B', 'failure'],
                              ['crash', 'B', 'error_state'],
                          ])
        m.go()
        assert m.state == 'B'
        m.succeed()
        assert m.get_state(m.state).is_accepted
        m.set_state('B')
        m.fail_accepted()
        assert m.get_state(m.state).is_accepted
        m.set_state('B')
        with pytest.raises(MachineError):
            m.crash()  # error_state is not accepted


# ---------------------------------------------------------------------------
# Pickle / serialization tests
# ---------------------------------------------------------------------------


class TestPickle:
    """Tests for pickling machines."""

    def test_pickle_locked_machine(self):
        """A user pickles and unpickles a LockedMachine, verifying independent state."""
        from transitions.extensions.locking import LockedMachine

        m1 = LockedMachine(states=['A', 'B', 'C'], initial='A',
                           transitions=[['go', 'A', 'B'], ['go', 'B', 'C']],
                           auto_transitions=False)
        m1.go()
        assert m1.state == 'B'

        dump = pickle.dumps(m1)
        m2 = pickle.loads(dump)
        assert m2.state == 'B'
        assert m2.is_B()

        # Verify independence
        m2.go()
        assert m2.state == 'C'
        assert m1.state == 'B'  # unchanged

    def test_pickle_hierarchical_locked_machine(self):
        """A user pickles and unpickles a LockedHierarchicalMachine with nested state."""
        from transitions.extensions.factory import MachineFactory

        cls = MachineFactory.get_predefined(nested=True, locked=True)
        states = ['A', {'name': 'B', 'children': ['1', '2'], 'initial': '1'}]
        m1 = cls(states=states, initial='A',
                 transitions=[['go', 'A', 'B']], auto_transitions=True)
        m1.go()
        assert m1.state == 'B_1'

        dump = pickle.dumps(m1)
        m2 = pickle.loads(dump)
        assert m2.state == 'B_1'
        assert m2.is_B(allow_substates=True)

        m2.to_B_2()
        assert m2.state == 'B_2'
        assert m1.state == 'B_1'  # original unchanged


# ---------------------------------------------------------------------------
# model_override tests
# ---------------------------------------------------------------------------


class TestModelOverride:
    """Tests for model_override mode where only pre-declared methods are overridden."""

    def test_model_override_basic_and_dynamic(self):
        """A user uses model_override for selective method assignment and dynamic state addition."""
        from transitions import Machine

        class Model:
            def trigger(self, name: str) -> bool:
                raise RuntimeError("Should be overridden")
            def is_A(self) -> bool:
                raise RuntimeError("Should be overridden")
            def is_C(self) -> bool:
                raise RuntimeError("Should be overridden")

        model = Model()
        machine = Machine(model, states=["A", "B"], initial="A", model_override=True)
        assert model.is_A()
        with pytest.raises(AttributeError):
            model.to_B()  # not declared on model
        assert model.trigger("to_B")
        assert not model.is_A()

        # Dynamic: add_state creates is_C because it's declared on model
        with pytest.raises(RuntimeError):
            model.is_C()  # not overridden yet
        machine.add_state("C")
        assert not model.is_C()
        model.trigger("to_C")
        assert model.is_C()


# ---------------------------------------------------------------------------
# Complex end-to-end scenarios
# ---------------------------------------------------------------------------


class TestComplexScenarios:
    """End-to-end tests combining multiple features."""

    def test_nested_machine_with_enum_states_and_markup(self):
        """A user combines HierarchicalMarkupMachine with enum-member substates for a round-trip."""
        from transitions.extensions.markup import HierarchicalMarkupMachine

        class Phase(Enum):
            INIT = 1
            RUNNING = 2
            DONE = 3

        m1 = HierarchicalMarkupMachine(
            states=[
                'idle',
                {'name': 'active', 'children': Phase, 'initial': Phase.INIT}
            ],
            transitions=[
                ['start', 'idle', 'active'],
                ['run', 'active_INIT', 'active_RUNNING'],
                ['finish', 'active_RUNNING', 'active_DONE'],
            ],
            initial='idle',
            auto_transitions=False,
        )
        markup = m1.markup

        # The enum members are serialized under the parent's 'children' as their member names.
        active_state = [s for s in markup['states'] if s['name'] == 'active'][0]
        child_names = [ch['name'] for ch in active_state['children']]
        assert child_names == ['INIT', 'RUNNING', 'DONE']

        # The serialized markup recreates a working machine whose enum-named substates survive.
        m2 = HierarchicalMarkupMachine(markup=markup)
        m2.start()
        assert m2.state == 'active_INIT'
        assert m2.is_active(allow_substates=True)
        m2.run()
        assert m2.state == 'active_RUNNING'
        m2.finish()
        assert m2.state == 'active_DONE'

    def test_final_states_flat_and_nested(self):
        """A user uses final states with on_final in both flat and nested machines."""
        from transitions import Machine, State
        from transitions.extensions.nesting import HierarchicalMachine

        # Flat: final + queued + on_final
        log = []
        class Model:
            def finalize(self):
                log.append('finalized')

        model = Model()
        Machine(model=model,
                states=['running', State('complete', final=True)],
                transitions=[['finish', 'running', 'complete']],
                initial='running', queued=True,
                on_final='finalize', auto_transitions=False)
        model.finish()
        assert model.state == 'complete'
        assert 'finalized' in log

        # Nested: final substate triggers on_final
        log2 = []
        states = ['A', {'name': 'B', 'children': [
            'step1', {'name': 'step2', 'final': True}
        ]}]
        m = HierarchicalMachine(states=states, initial='A', auto_transitions=False,
                                 on_final=lambda: log2.append('final_fired'))
        m.add_transition('go', 'A', 'B_step1')
        m.add_transition('advance', 'B_step1', 'B_step2')
        m.go()
        assert len(log2) == 0
        m.advance()
        assert m.state == 'B_step2'
        assert 'final_fired' in log2

    def test_callback_resolution_and_arg_passing(self):
        """A user relies on auto-discovered on_enter/on_exit callbacks and passes args through triggers."""
        from transitions import Machine

        log = []
        received = {}

        class Model:
            def on_enter_B(self):
                log.append('entered_B')
            def on_exit_B(self, *args, **kwargs):
                log.append('exited_B')
            def on_enter_C(self, *args, **kwargs):
                log.append('entered_C')
            def before_advance(self, speed, direction='north'):
                received['speed'] = speed
                received['direction'] = direction

        model = Model()
        m = Machine(model=model, states=['A', 'B', 'C'], initial='A', auto_transitions=False)
        m.add_transition('go', 'A', 'B')
        m.add_transition('advance', 'B', 'C', before='before_advance')

        model.go()
        assert model.state == 'B'
        assert log == ['entered_B']

        model.advance(42, direction='south')
        assert model.state == 'C'
        assert log == ['entered_B', 'exited_B', 'entered_C']
        assert received['speed'] == 42
        assert received['direction'] == 'south'

    def test_unless_and_partial_conditions(self):
        """A user uses 'unless' and functools.partial as conditions on transitions."""
        from functools import partial
        from transitions import Machine

        # unless blocks transition
        class Model:
            blocked = True
            def is_blocked(self):
                return self.blocked

        model = Model()
        Machine(model=model, states=['A', 'B'], initial='A',
                transitions=[{'trigger': 'go', 'source': 'A', 'dest': 'B',
                              'unless': 'is_blocked'}],
                ignore_invalid_triggers=True, auto_transitions=False)
        result = model.go()
        assert result is False
        assert model.state == 'A'
        model.blocked = False
        result = model.go()
        assert result is True
        assert model.state == 'B'

        # partial as condition
        def threshold_check(limit, event_data):
            return event_data.kwargs.get('value', 0) > limit

        model2 = type('Obj', (), {})()
        m2 = Machine(model=model2, states=['low', 'high'], initial='low',
                     send_event=True, auto_transitions=False)
        m2.add_transition('check', 'low', 'high', conditions=[partial(threshold_check, 10)])
        assert model2.check(value=5) is False
        assert model2.state == 'low'
        assert model2.check(value=15) is True
        assert model2.state == 'high'



# ---------------------------------------------------------------------------
# AsyncMachine integration tests
# ---------------------------------------------------------------------------


class TestAsyncIntegration:
    """Integration tests for AsyncMachine — async state machines with async callbacks."""

    def test_async_workflow_queued_and_timeout(self):
        """A user creates AsyncMachine with callbacks, queued chains, and AsyncTimeout."""
        from transitions.extensions.asyncio import AsyncMachine, AsyncTimeout
        from transitions.extensions.states import add_state_features

        async def run():
            # Basic async workflow with conditions and callbacks
            log = []
            async def async_before():
                await asyncio.sleep(0.01)
                log.append('before')
            async def async_after():
                await asyncio.sleep(0.01)
                log.append('after')
            async def async_condition():
                await asyncio.sleep(0.01)
                return True

            m = AsyncMachine(
                states=['idle', 'processing', 'done'],
                initial='idle', auto_transitions=False,
                transitions=[
                    {'trigger': 'start', 'source': 'idle', 'dest': 'processing',
                     'conditions': async_condition, 'before': async_before, 'after': async_after},
                    {'trigger': 'finish', 'source': 'processing', 'dest': 'done'},
                ],
            )
            await m.start()
            assert m.state == 'processing'
            assert log == ['before', 'after']

            # Async queued chain
            chain_log = []
            class Model:
                pass
            model = Model()
            m2 = AsyncMachine(model=model, states=['A', 'B', 'C', 'D'], initial='A',
                              queued=True, auto_transitions=False)
            async def chain_to_c():
                chain_log.append('c')
                await model.to_c()
            async def chain_to_d():
                chain_log.append('d')
                await model.to_d()
            m2.add_transition('to_b', 'A', 'B', after=chain_to_c)
            m2.add_transition('to_c', 'B', 'C', after=chain_to_d)
            m2.add_transition('to_d', 'C', 'D')
            await model.to_b()
            assert model.state == 'D'
            assert chain_log == ['c', 'd']

            # AsyncTimeout
            timeout_log = []
            @add_state_features(AsyncTimeout)
            class CustomAsyncMachine(AsyncMachine):
                pass
            async def on_timeout():
                timeout_log.append('timed_out')
            m3 = CustomAsyncMachine(
                states=['idle', {'name': 'waiting', 'timeout': 0.1, 'on_timeout': on_timeout}],
                initial='idle', auto_transitions=True,
                transitions=[['start', 'idle', 'waiting']],
            )
            await m3.start()
            assert m3.state == 'waiting'
            await asyncio.sleep(0.3)
            assert 'timed_out' in timeout_log

            # Per-model queuing (queued='model')
            class Obj:
                pass
            pm1, pm2 = Obj(), Obj()
            m4 = AsyncMachine(model=[pm1, pm2], states=['A', 'B', 'C'], initial='A',
                              queued='model', auto_transitions=False)
            m4.add_transition('go', 'A', 'B')
            m4.add_transition('advance', 'B', 'C')
            await pm1.go()
            assert pm1.state == 'B'
            assert pm2.state == 'A'  # independent queue
            await pm2.go()
            await pm1.advance()
            assert pm1.state == 'C'
            assert pm2.state == 'B'

        asyncio.run(run())

    def test_hierarchical_async_machine(self):
        """A user creates a HierarchicalAsyncMachine with nested states and async callbacks."""
        from transitions.extensions.asyncio import HierarchicalAsyncMachine

        log = []

        async def on_enter_active_step1():
            log.append('enter_step1')

        async def on_exit_active_step1():
            log.append('exit_step1')

        async def run():
            class Model:
                async def on_enter_active_step1(self):
                    log.append('enter_step1')
                async def on_exit_active_step1(self):
                    log.append('exit_step1')

            model = Model()
            states = [
                'idle',
                {'name': 'active', 'children': ['step1', 'step2'], 'initial': 'step1'},
                'done',
            ]
            m = HierarchicalAsyncMachine(
                model=model,
                states=states,
                initial='idle',
                auto_transitions=False,
                transitions=[
                    ['start', 'idle', 'active'],
                    ['advance', 'active_step1', 'active_step2'],
                    ['finish', 'active', 'done'],
                ],
            )
            assert model.state == 'idle'
            await model.start()
            assert model.state == 'active_step1'
            assert 'enter_step1' in log

            await model.advance()
            assert model.state == 'active_step2'
            assert 'exit_step1' in log

            await model.finish()
            assert model.state == 'done'

        asyncio.run(run())

    def test_async_callback_order(self):
        """A user verifies the callback execution order in AsyncMachine matches the sync order."""
        from transitions.extensions.asyncio import AsyncMachine

        async def run():
            log = []

            class Model:
                async def global_prepare(self):
                    log.append('global_prepare')
                async def trans_prepare(self):
                    log.append('trans_prepare')
                async def trans_condition(self):
                    log.append('trans_condition')
                    return True
                async def global_before(self):
                    log.append('global_before')
                async def trans_before(self):
                    log.append('trans_before')
                async def on_exit_A(self):
                    log.append('exit_A')
                async def on_enter_B(self):
                    log.append('enter_B')
                async def trans_after(self):
                    log.append('trans_after')
                async def global_after(self):
                    log.append('global_after')
                async def global_finalize(self):
                    log.append('global_finalize')

            model = Model()
            AsyncMachine(
                model=model, states=['A', 'B'], initial='A',
                transitions=[{
                    'trigger': 'go', 'source': 'A', 'dest': 'B',
                    'prepare': 'trans_prepare',
                    'conditions': 'trans_condition',
                    'before': 'trans_before',
                    'after': 'trans_after',
                }],
                prepare_event='global_prepare',
                before_state_change='global_before',
                after_state_change='global_after',
                finalize_event='global_finalize',
                auto_transitions=False,
            )
            await model.go()
            assert log == [
                'global_prepare', 'trans_prepare', 'trans_condition',
                'global_before', 'trans_before', 'exit_A', 'enter_B',
                'trans_after', 'global_after', 'global_finalize'
            ]

        asyncio.run(run())


# ---------------------------------------------------------------------------
# Dispatch and multi-model tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Nested final states and ignore_invalid_triggers
# ---------------------------------------------------------------------------


class TestNestedAdvanced:
    """Tests for advanced nesting behaviors."""

    def test_nested_ignore_invalid_triggers(self):
        """A user combines nested states with ignore_invalid_triggers to suppress errors."""
        from transitions.extensions.nesting import HierarchicalMachine

        states = [
            'A',
            {'name': 'B', 'children': ['1', '2'], 'initial': '1'}
        ]
        m = HierarchicalMachine(states=states, initial='A',
                                 ignore_invalid_triggers=True, auto_transitions=False)
        m.add_transition('go', 'A', 'B')
        m.add_transition('advance', 'B_1', 'B_2')
        m.add_transition('back', 'B', 'A')

        m.go()
        assert m.state == 'B_1'
        result = m.advance()
        assert m.state == 'B_2'
        result = m.advance()
        assert result is False
        assert m.state == 'B_2'
        m.back()
        assert m.state == 'A'
        m.go()
        assert m.state == 'B_1'



# ---------------------------------------------------------------------------
# Graph/Diagram generation tests
# ---------------------------------------------------------------------------


class TestGraphIntegration:
    """Tests for GraphMachine diagram generation."""

    def test_graph_machine_dot_output(self):
        """A user creates a GraphMachine with conditions and verifies DOT output structure."""
        from transitions.extensions.diagrams import GraphMachine

        class Model:
            def is_ready(self): return True

        model = Model()
        m = GraphMachine(model=model, states=['idle', 'running', 'done'],
                         transitions=[
                             {'trigger': 'start', 'source': 'idle', 'dest': 'running',
                              'conditions': 'is_ready'},
                             {'trigger': 'finish', 'source': 'running', 'dest': 'done'},
                         ],
                         initial='idle', auto_transitions=False,
                         show_conditions=True, title='Workflow')

        g = m.get_graph()
        src = g.source

        assert 'idle' in src
        assert 'running' in src
        assert 'done' in src
        assert 'start' in src
        assert 'finish' in src
        assert 'Workflow' in src
        assert 'is_ready' in src  # condition shown in edge label

        # Active state should have distinct styling from inactive states
        lines = [l.strip() for l in src.split('\n')]
        idle_lines = [l for l in lines if l.startswith('idle')]
        running_lines = [l for l in lines if l.startswith('running')]
        assert idle_lines and running_lines
        assert idle_lines[0] != running_lines[0]

        model.start()
        g2 = m.get_graph()
        src2 = g2.source
        lines2 = [l.strip() for l in src2.split('\n')]
        running_lines2 = [l for l in lines2 if l.startswith('running')]
        idle_lines2 = [l for l in lines2 if l.startswith('idle')]
        assert running_lines2[0] != idle_lines2[0]

        # show_conditions=False should hide condition names from edges
        m2 = GraphMachine(model=Model(), states=['X', 'Y'],
                          transitions=[{'trigger': 'go', 'source': 'X', 'dest': 'Y',
                                        'conditions': 'is_ready'}],
                          initial='X', show_conditions=False)
        src3 = m2.get_graph().source
        assert 'go' in src3
        assert 'is_ready' not in src3  # condition hidden when show_conditions=False

    def test_graph_machine_with_nested_states(self):
        """A user creates a hierarchical GraphMachine via factory and checks subgraph structure."""
        from transitions.extensions.factory import MachineFactory

        cls = MachineFactory.get_predefined(graph=True, nested=True)
        states = ['A', {'name': 'B', 'children': ['1', '2'], 'initial': '1'}]
        m = cls(states=states, initial='A', auto_transitions=False,
                transitions=[['go', 'A', 'B'], ['back', 'B', 'A']])
        g = m.get_graph()
        src = g.source

        assert 'subgraph' in src.lower() or 'cluster' in src.lower()
        assert 'go' in src
        assert 'back' in src


# ---------------------------------------------------------------------------
# Advanced core tests
# ---------------------------------------------------------------------------


class TestAdvancedCore:
    """Tests for advanced core Machine features."""

    def test_custom_transition_subclass(self):
        """A user overrides the Transition class for both flat and hierarchical machines."""
        from transitions import Machine, Transition
        from transitions.extensions.nesting import HierarchicalMachine, NestedTransition

        class LoggedTransition(Transition):
            def __init__(self, *args, **kwargs):
                self.execution_count = 0
                super().__init__(*args, **kwargs)

            def execute(self, event_data):
                self.execution_count += 1
                return super().execute(event_data)

        class CustomMachine(Machine):
            transition_cls = LoggedTransition

        m = CustomMachine(states=['A', 'B', 'C'],
                          transitions=[['go', 'A', 'B'], ['go', 'B', 'C']],
                          initial='A', auto_transitions=False)
        m.go()
        assert m.state == 'B'
        trans = m.get_transitions(trigger='go')
        assert all(isinstance(t, LoggedTransition) for t in trans)
        a_to_b = [t for t in trans if t.source == 'A'][0]
        assert a_to_b.execution_count == 1

        # Custom transition_cls with HierarchicalMachine requires NestedTransition subclass
        class CountedNestedTransition(NestedTransition):
            count = 0
            def execute(self, event_data):
                CountedNestedTransition.count += 1
                return super().execute(event_data)

        class CustomHM(HierarchicalMachine):
            transition_cls = CountedNestedTransition

        m2 = CustomHM(states=['X', {'name': 'Y', 'children': ['1', '2'], 'initial': '1'}],
                      transitions=[['enter', 'X', 'Y'], ['advance', 'Y_1', 'Y_2']],
                      initial='X', auto_transitions=False)
        m2.enter()
        m2.advance()
        assert m2.state == 'Y_2'
        assert CountedNestedTransition.count == 2
        assert isinstance(m2.get_transitions(trigger='enter')[0], CountedNestedTransition)



# ---------------------------------------------------------------------------
# Advanced nesting tests
# ---------------------------------------------------------------------------


class TestNestingAdvanced:
    """Tests for advanced nesting behaviors beyond basic parent/child."""

    def test_transitions_defined_inside_nested_states(self):
        """A user defines transitions inside a nested state dict using the 'transitions' key."""
        from transitions.extensions.nesting import HierarchicalMachine

        states = [
            'A',
            {'name': 'B', 'children': ['1', '2'],
             'transitions': [['step', '1', '2']]}
        ]
        m = HierarchicalMachine(states=states, initial='A', auto_transitions=False)
        m.add_transition('enter', 'A', 'B_1')
        m.add_transition('leave', 'B', 'A')

        m.enter()
        assert m.state == 'B_1'
        m.step()
        assert m.state == 'B_2'
        m.leave()
        assert m.state == 'A'


# ---------------------------------------------------------------------------
# Async parallel states
# ---------------------------------------------------------------------------


class TestAsyncParallel:
    """Tests for async machines with parallel states."""

    def test_hierarchical_async_with_parallel_states(self):
        """A user creates a HierarchicalAsyncMachine with parallel substates and async callbacks."""
        from transitions.extensions.asyncio import HierarchicalAsyncMachine

        async def run():
            log = []

            class Model:
                async def on_enter_P_1_a(self):
                    log.append('enter_P_1_a')
                async def on_enter_P_2_x(self):
                    log.append('enter_P_2_x')

            model = Model()
            states = ['A', {'name': 'P', 'parallel': [
                {'name': '1', 'children': ['a', 'b'], 'initial': 'a'},
                {'name': '2', 'children': ['x', 'y'], 'initial': 'x'}
            ]}]
            m = HierarchicalAsyncMachine(model=model, states=states, initial='A',
                                          auto_transitions=False)
            m.add_transition('enter_p', 'A', 'P')
            m.add_transition('reset', 'P', 'A')

            await model.enter_p()
            assert isinstance(model.state, list)
            assert 'P_1_a' in model.state
            assert 'P_2_x' in model.state
            assert 'enter_P_1_a' in log
            assert 'enter_P_2_x' in log

            await model.reset()
            assert model.state == 'A'

        asyncio.run(run())


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for subtle edge-case behaviors."""

    def test_sibling_transition_does_not_fire_parent_callbacks(self):
        """A user transitions between sibling substates; parent on_exit/on_enter must NOT fire."""
        from transitions.extensions.nesting import HierarchicalMachine

        parent_exit = MagicMock()
        parent_enter = MagicMock()
        child_exit = MagicMock()
        child_enter = MagicMock()

        class Model:
            def on_exit_A(self): parent_exit()
            def on_enter_A(self): parent_enter()
            def on_exit_A_1(self): child_exit()
            def on_enter_A_2(self): child_enter()

        model = Model()
        states = [{'name': 'A', 'children': ['1', '2'], 'initial': '1'}, 'B']
        m = HierarchicalMachine(model=model, states=states, initial='A', auto_transitions=False)
        m.add_transition('switch', 'A_1', 'A_2')
        m.add_transition('leave', 'A', 'B')

        parent_exit.reset_mock()
        parent_enter.reset_mock()

        model.switch()  # sibling transition
        assert model.state == 'A_2'
        assert child_exit.call_count == 1
        assert child_enter.call_count == 1
        assert parent_exit.call_count == 0  # parent NOT exited
        assert parent_enter.call_count == 0  # parent NOT re-entered

        model.leave()  # crosses parent boundary
        assert model.state == 'B'
        assert parent_exit.call_count == 1  # NOW parent exits

    def test_parallel_final_requires_all_children(self):
        """A user verifies on_final fires only when ALL parallel children reach final states."""
        from transitions.extensions.nesting import HierarchicalMachine

        final_parent = MagicMock()
        final_machine = MagicMock()

        states = ['A', {'name': 'P', 'parallel': [
            {'name': 'X', 'children': [
                'running', {'name': 'done', 'final': True}
            ], 'initial': 'running', 'transitions': [['finish_x', 'running', 'done']]},
            {'name': 'Y', 'children': [
                'running', {'name': 'done', 'final': True}
            ], 'initial': 'running', 'transitions': [['finish_y', 'running', 'done']]},
        ], 'on_final': final_parent}]

        m = HierarchicalMachine(states=states, initial='A',
                                 on_final=final_machine, auto_transitions=False)
        m.add_transition('start', 'A', 'P')
        m.start()

        m.finish_x()  # only X is done
        assert final_parent.call_count == 0  # NOT yet — Y still running
        assert final_machine.call_count == 0

        m.finish_y()  # now both done
        assert final_parent.call_count == 1  # NOW fires
        assert final_machine.call_count == 1

    def test_callback_duplication_global_and_per_transition(self):
        """A user registers the same callback globally and per-transition; it runs twice for each type."""
        from transitions import Machine

        before_mock = MagicMock()
        after_mock = MagicMock()
        prepare_mock = MagicMock()

        class Model:
            def my_before(self): before_mock()
            def my_after(self): after_mock()
            def my_prepare(self): prepare_mock()

        model = Model()
        Machine(model=model, states=['A', 'B'], initial='A',
                transitions=[{'trigger': 'go', 'source': 'A', 'dest': 'B',
                              'before': 'my_before', 'after': 'my_after',
                              'prepare': 'my_prepare'}],
                before_state_change='my_before',
                after_state_change='my_after',
                prepare_event='my_prepare',
                auto_transitions=False)
        model.go()
        assert before_mock.call_count == 2  # global + per-transition
        assert after_mock.call_count == 2
        assert prepare_mock.call_count == 2

    def test_parallel_reflexive_does_not_exit_sibling(self):
        """A user fires a reflexive transition in one parallel branch; sibling branch stays untouched."""
        from transitions.extensions.nesting import HierarchicalMachine

        exit_c_1 = MagicMock()

        states = ['A', {'name': 'C', 'parallel': [
            {'name': '1', 'on_exit': exit_c_1},
            '2'
        ]}]
        m = HierarchicalMachine(states=states,
                                transitions=[['test', 'C_2', 'C_2']],
                                initial='C')
        assert isinstance(m.state, list)
        m.test()
        assert isinstance(m.state, list)
        assert 'C_1' in m.state
        assert 'C_2' in m.state
        assert exit_c_1.call_count == 0

    def test_exception_in_nested_enter_resets_scope(self):
        """A user's on_enter callback raises; machine must remain usable for subsequent transitions."""
        from transitions.extensions.nesting import HierarchicalMachine

        class Model:
            def on_enter_B_1(self):
                raise RuntimeError("Oh no!")

        states = ['A',
                  {'name': 'B', 'initial': '1', 'children': ['1', '2']},
                  {'name': 'C', 'initial': '1', 'children': ['1', '2']}]
        model = Model()
        machine = HierarchicalMachine(model, states=states, initial='A')

        with pytest.raises(RuntimeError):
            model.to_B()
        assert model.is_B_1()

        machine.set_state('A', model)
        with pytest.raises(RuntimeError):
            model.to_B()

        machine.set_state('A', model)
        model.to_C()
        assert model.is_C_1()

    def test_nested_enum_states(self):
        """A user uses Enum members as children of a nested state."""
        from transitions.extensions.nesting import HierarchicalMachine

        class Phase(Enum):
            INIT = 1
            RUNNING = 2
            DONE = 3

        states = ['idle', {'name': 'active', 'children': Phase, 'initial': Phase.INIT}]
        m = HierarchicalMachine(states=states, initial='idle', auto_transitions=False)
        m.add_transition('start', 'idle', 'active')
        m.add_transition('run', 'active_INIT', 'active_RUNNING')
        m.add_transition('finish', 'active_RUNNING', 'active_DONE')

        m.start()
        assert m.state == Phase.INIT
        assert m.is_active(allow_substates=True)
        m.run()
        assert m.state == Phase.RUNNING
        m.finish()
        assert m.state == Phase.DONE
        assert m.is_active(allow_substates=True)

    def test_parallel_within_parallel_state_structure(self):
        """A user creates nested parallel states (parallel inside parallel) and initializes from that state."""
        from transitions.extensions.nesting import HierarchicalMachine

        states = ['A',
                  {'name': 'B',
                   'parallel': [
                       {'name': '1', 'parallel': [
                           {'name': 'a', 'children': ['x', 'y', 'z'], 'initial': 'z'},
                           {'name': 'b', 'children': ['x', 'y', 'z'], 'initial': 'y'}
                       ]},
                       {'name': '2', 'children': ['a', 'b', 'c'], 'initial': 'a'},
                   ]}]

        m = HierarchicalMachine(states=states, initial='A')
        m.to_B()
        expected = [['B_1_a_z', 'B_1_b_y'], 'B_2_a']
        assert m.state == expected

        m2 = HierarchicalMachine(states=states, initial=m.state)
        assert m2.state == expected

        m.to_A()
        assert m.state == 'A'

