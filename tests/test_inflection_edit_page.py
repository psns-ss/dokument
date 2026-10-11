"""
Tests for edit_inflection page (GET/POST /debug/inflections/<id>/edit)
and merge via conflict resolution.

Per-test DB isolation comes from the shared `fresh_inflection_db` fixture
(conftest.py).
"""


class TestGetWord:
    """inflection_db.get_word() helper."""

    def test_returns_word(self, fresh_inflection_db):
        word_id = fresh_inflection_db.save_word({"no": "Стол", "ge": "Стола", "da": "Стол"})
        result = fresh_inflection_db.get_word(word_id)
        assert result is not None
        assert result["word_id"] == word_id
        assert result["forms"]["no"] == "Стол"
        assert result["nominative"] == "Стол"

    def test_returns_none_for_missing(self, fresh_inflection_db):
        assert fresh_inflection_db.get_word(99999) is None

    def test_nominative_falls_back_to_headword_when_no_no_case(self, fresh_inflection_db):
        # No 'no' form -> headword is the first case-ordered form (ge here).
        word_id = fresh_inflection_db.save_word({"ge": "Чего-то", "da": "Чему-то"})
        result = fresh_inflection_db.get_word(word_id)
        assert result is not None
        assert result["nominative"] == "Чего-то"


class TestGetConflictWithWords:
    """inflection_db.get_conflict_with_words() helper."""

    def test_returns_conflict_with_word_data(self, fresh_inflection_db):
        # Create overlapping entries to trigger a conflict
        fresh_inflection_db.save_word({"no": "A", "ge": "G1", "da": "D1"})
        fresh_inflection_db.save_word({"no": "B", "ge": "G2", "da": "D2"})
        fresh_inflection_db.save_word({"no": "A", "da": "D2"})  # conflicts: A maps to word1, da:D2 maps to word2

        conflicts = fresh_inflection_db.get_conflicts()
        assert len(conflicts) >= 1

        result = fresh_inflection_db.get_conflict_with_words(conflicts[0]["id"])
        assert result is not None
        assert "existing_word" in result
        assert "new_word" in result
        assert result["existing_word"] is not None

    def test_returns_none_for_missing(self, fresh_inflection_db):
        assert fresh_inflection_db.get_conflict_with_words(99999) is None


class TestEditPageGET:
    """GET /debug/inflections/<id>/edit — edit form."""

    def test_edit_page_200(self, client, fresh_inflection_db):
        word_id = fresh_inflection_db.save_word({"no": "Стол", "ge": "Стола"})
        response = client.get(f'/debug/inflections/{word_id}/edit')
        assert response.status_code == 200
        data = response.get_data(as_text=True)
        assert 'Стол' in data
        assert 'Редактирование' in data

    def test_edit_page_404_redirect(self, client, fresh_inflection_db):
        response = client.get('/debug/inflections/99999/edit')
        assert response.status_code in (302, 200)  # redirect or flash

    def test_edit_page_shows_cases(self, client, fresh_inflection_db):
        word_id = fresh_inflection_db.save_word({"no": "Стол", "ge": "Стола", "da": "Стол"})
        response = client.get(f'/debug/inflections/{word_id}/edit')
        data = response.get_data(as_text=True)
        assert 'Стола' in data
        assert 'input' in data.lower()

    def test_edit_page_with_merge_param(self, client, fresh_inflection_db):
        """Conflict merge context loads both words."""
        fresh_inflection_db.save_word({"no": "A", "ge": "G1", "da": "D1"})
        fresh_inflection_db.save_word({"no": "B", "ge": "G2", "da": "D2"})
        fresh_inflection_db.save_word({"no": "A", "da": "D2"})  # creates conflict

        conflicts = fresh_inflection_db.get_conflicts()
        assert len(conflicts) >= 1
        conflict_id = conflicts[0]["id"]
        existing_word_id = conflicts[0]["existing_word_id"]

        response = client.get(f'/debug/inflections/{existing_word_id}/edit?merge={conflict_id}')
        assert response.status_code == 200
        data = response.get_data(as_text=True)
        assert 'конфликт' in data.lower() or 'Conflict' in data or 'merge' in data.lower() or str(conflict_id) in data

    def test_merge_page_renders_named_conflict_fields(self, client, fresh_inflection_db):
        """#12: a disputed case renders a case_<code> radio + uniquely-named
        value_<code>_<idx> inputs, so the server can read the chosen option
        without relying on JS. Here existing=word2 (no:B), new=word1 (no:A),
        so 'no' is disputed."""
        fresh_inflection_db.save_word({"no": "A", "ge": "G1", "da": "D1"})
        fresh_inflection_db.save_word({"no": "B", "ge": "G2", "da": "D2"})
        fresh_inflection_db.save_word({"no": "A", "da": "D2"})  # split conflict

        conflicts = fresh_inflection_db.get_conflicts()
        existing_word_id = conflicts[0]["existing_word_id"]
        data = client.get(
            f'/debug/inflections/{existing_word_id}/edit?merge={conflicts[0]["id"]}'
        ).get_data(as_text=True)
        assert 'name="case_no"' in data
        assert 'name="value_no_0"' in data  # existing (B)
        assert 'name="value_no_1"' in data  # new (A)

    def test_edit_page_merge_invalid_conflict(self, client, fresh_inflection_db):
        word_id = fresh_inflection_db.save_word({"no": "Стол", "ge": "Стола"})
        response = client.get(f'/debug/inflections/{word_id}/edit?merge=99999')
        assert response.status_code in (302, 200)


class TestEditPagePOST:
    """POST /debug/inflections/<id>/edit — save changes."""

    def test_save_edited_forms(self, client, fresh_inflection_db):
        word_id = fresh_inflection_db.save_word({"no": "Стол", "ge": "Стола"})

        response = client.post(
            f'/debug/inflections/{word_id}/edit',
            data={'case': ['no', 'ge', 'da'], 'value': ['Стол', 'Стола', 'Столу']},
            follow_redirects=False
        )
        assert response.status_code == 302  # redirect after save

        # Verify the forms were saved
        result = fresh_inflection_db.lookup_by_form("no", "Стол")
        assert result is not None
        assert "da" in result

    def test_save_empty_values_skipped(self, client, fresh_inflection_db):
        word_id = fresh_inflection_db.save_word({"no": "Стол", "ge": "Стола"})

        response = client.post(
            f'/debug/inflections/{word_id}/edit',
            data={'case': ['no', 'ge'], 'value': ['Стол', '']},
            follow_redirects=False
        )
        assert response.status_code == 302

    def test_collect_forms_reads_conflict_radio_server_side(self, client):
        """#12: a disputed case's chosen option is read from its radio + named
        value inputs server-side. The old JS rename-on-submit made the 'new'
        value win when JS was off; here there is no JS, so the radio must decide."""
        from routes.debug import _collect_forms
        with client.application.test_request_context(
            method='POST',
            data={
                'case': ['no', 'ge'],            # simple cases (parallel lists)
                'value': ['Стол', 'Стола'],
                'case_da': '0',                  # disputed 'da': pick existing
                'value_da_0': 'Столу',
                'value_da_1': 'Стол (новый)',    # new — must be ignored
            }
        ):
            assert _collect_forms(['da']) == {'no': 'Стол', 'ge': 'Стола', 'da': 'Столу'}

    def test_collect_forms_reads_new_option_when_selected(self, client):
        """#12: picking the 'new' option (idx 1) yields the new value — the read
        is order-independent (no last-wins), unlike the old parallel-list zip."""
        from routes.debug import _collect_forms
        with client.application.test_request_context(
            method='POST',
            data={
                'case': ['no'],
                'value': ['Стол'],
                'case_da': '1',
                'value_da_0': 'Столу',
                'value_da_1': 'Стол (новый)',
            }
        ):
            assert _collect_forms(['da']) == {'no': 'Стол', 'da': 'Стол (новый)'}

    def test_collect_forms_ignores_conflict_code_not_posted(self, client):
        """#12: a conflict code with no radio in the payload is skipped (a stale
        or hand-crafted form can't inject a value under a disputed case)."""
        from routes.debug import _collect_forms
        with client.application.test_request_context(
            method='POST',
            data={'case': ['no'], 'value': ['Стол'], 'value_da_1': 'Стол (новый)'}
        ):
            assert _collect_forms(['da']) == {'no': 'Стол'}

    def test_merge_via_edit_page(self, client, fresh_inflection_db):
        """Resolve a conflict via the edit page using the REAL form shape: each
        disputed case posts its case_<code> radio + value_<code>_<idx> inputs
        (no parallel lists — all three cases differ here). The admin's per-case
        choice is applied, the new word is folded in + deleted, conflict gone."""
        word1 = fresh_inflection_db.save_word({"no": "A", "ge": "G1", "da": "D1"})   # new
        word2 = fresh_inflection_db.save_word({"no": "B", "ge": "G2", "da": "D2"})   # existing
        fresh_inflection_db.save_word({"no": "A", "da": "D2"})  # split conflict

        conflicts = fresh_inflection_db.get_conflicts()
        conflict_id = conflicts[0]["id"]
        existing_word_id = conflicts[0]["existing_word_id"]
        assert existing_word_id == word2

        # Admin picks the "new" (idx 1) option for every disputed case.
        response = client.post(
            f'/debug/inflections/{existing_word_id}/edit',
            data={
                '_merge': str(conflict_id),
                'case_no': '1', 'value_no_0': 'B', 'value_no_1': 'A',
                'case_ge': '1', 'value_ge_0': 'G2', 'value_ge_1': 'G1',
                'case_da': '1', 'value_da_0': 'D2', 'value_da_1': 'D1',
            },
            follow_redirects=False
        )
        assert response.status_code == 302

        # Conflict dismissed; the existing word now holds the chosen (new) forms;
        # the new word was folded in and deleted.
        remaining_ids = [c["id"] for c in fresh_inflection_db.get_conflicts()]
        assert conflict_id not in remaining_ids
        assert fresh_inflection_db.get_word(existing_word_id)["forms"] == {"no": "A", "ge": "G1", "da": "D1"}
        assert fresh_inflection_db.get_word(word1) is None

    def test_merge_rejects_mismatched_word_id(self, client, fresh_inflection_db):
        """A merge URL pointing at a different word_id must be rejected, not applied."""
        fresh_inflection_db.save_word({"no": "A", "ge": "G1", "da": "D1"})
        fresh_inflection_db.save_word({"no": "B", "ge": "G2", "da": "D2"})
        fresh_inflection_db.save_word({"no": "A", "da": "D2"})  # creates conflict
        conflicts = fresh_inflection_db.get_conflicts()
        conflict_id = conflicts[0]["id"]

        # An unrelated word to target with the (wrong) merge URL.
        other_id = fresh_inflection_db.save_word({"no": "X", "ge": "X1"})

        response = client.post(
            f'/debug/inflections/{other_id}/edit',
            data={'_merge': str(conflict_id), 'case': ['no'], 'value': ['X']},
            follow_redirects=False
        )
        assert response.status_code == 302  # redirected away, not saved

        # Guard fired: conflict NOT dismissed, target word untouched.
        remaining_ids = [c["id"] for c in fresh_inflection_db.get_conflicts()]
        assert conflict_id in remaining_ids
        assert fresh_inflection_db.get_word(other_id) is not None

    def test_merge_empty_forms_dismisses_conflict(self, client, fresh_inflection_db):
        """Clearing all forms during a merge must still dismiss the conflict (no
        orphan). Real form shape: every disputed case's two value inputs emptied
        (the radio keeps its default idx 0)."""
        fresh_inflection_db.save_word({"no": "A", "ge": "G1", "da": "D1"})
        fresh_inflection_db.save_word({"no": "B", "ge": "G2", "da": "D2"})
        fresh_inflection_db.save_word({"no": "A", "da": "D2"})  # creates conflict
        conflicts = fresh_inflection_db.get_conflicts()
        conflict_id = conflicts[0]["id"]
        existing_word_id = conflicts[0]["existing_word_id"]

        response = client.post(
            f'/debug/inflections/{existing_word_id}/edit',
            data={
                '_merge': str(conflict_id),
                'case_no': '0', 'value_no_0': '', 'value_no_1': '',
                'case_ge': '0', 'value_ge_0': '', 'value_ge_1': '',
                'case_da': '0', 'value_da_0': '', 'value_da_1': '',
            },
            follow_redirects=False
        )
        assert response.status_code == 302

        # Conflict dismissed (not orphaned) and the existing word deleted.
        remaining_ids = [c["id"] for c in fresh_inflection_db.get_conflicts()]
        assert conflict_id not in remaining_ids
        assert fresh_inflection_db.get_word(existing_word_id) is None


class TestMissingWordRecovery:
    """#11: a conflict whose existing word was deleted offers recovery (discard /
    save-as-new) instead of orphaning the conflict."""

    @staticmethod
    def _make_split_conflict(db):
        """Two words + a split conflict; returns (conflict_id, existing_word_id,
        new_word_id). The split conflict's existing word is the non-'no' word."""
        db.save_word({"no": "A", "ge": "G1", "da": "D1"})   # word1 (preferred)
        word2 = db.save_word({"no": "B", "ge": "G2", "da": "D2"})
        db.save_word({"no": "A", "da": "D2"})               # split conflict
        conflict = db.get_conflicts()[0]
        return conflict["id"], conflict["existing_word_id"], conflict["new_word_id"], word2

    def test_merge_missing_existing_shows_recovery(self, client, fresh_inflection_db):
        conflict_id, existing_word_id, _, word2 = self._make_split_conflict(fresh_inflection_db)
        assert existing_word_id == word2
        fresh_inflection_db.delete_word(word2)  # delete the existing word

        response = client.get(f'/debug/inflections/{existing_word_id}/edit?merge={conflict_id}')
        assert response.status_code == 200
        data = response.get_data(as_text=True)
        assert 'Оригинальное слово отсутствует' in data
        assert f'/debug/inflections/new?from_conflict={conflict_id}' in data
        assert f'/debug/inflections/conflicts/{conflict_id}/dismiss' in data

    def test_new_word_prepopulated_from_conflict(self, client, fresh_inflection_db):
        conflict_id, _, _, _ = self._make_split_conflict(fresh_inflection_db)
        # The split conflict's submitted forms are {no:A, da:D2}.
        data = client.get(f'/debug/inflections/new?from_conflict={conflict_id}').get_data(as_text=True)
        assert f'конфликта #{conflict_id}' in data  # the source note
        assert 'value="A"' in data
        assert 'value="D2"' in data

    def test_new_word_form_carries_from_conflict_field(self, client, fresh_inflection_db):
        """The pre-populated new-word form must carry _from_conflict, so saving
        it dismisses the conflict. (The recovery link opens this form via
        ?from_conflict=<id> — without the hidden field the save would leave the
        conflict orphaned on the conflicts page.)"""
        conflict_id, _, _, _ = self._make_split_conflict(fresh_inflection_db)
        data = client.get(f'/debug/inflections/new?from_conflict={conflict_id}').get_data(as_text=True)
        assert f'name="_from_conflict" value="{conflict_id}"' in data

    def test_save_prepopulated_form_dismisses_conflict(self, client, fresh_inflection_db):
        """End-to-end: open the pre-populated form, then POST exactly what the
        form submits (case/value + the carried _from_conflict) — the conflict
        must be gone. This is the flow the recovery page drives."""
        conflict_id, existing_word_id, _, word2 = self._make_split_conflict(fresh_inflection_db)
        fresh_inflection_db.delete_word(word2)  # existing word gone

        # Mirror the form's fields (what the browser would POST on Save).
        response = client.post(
            '/debug/inflections/new',
            data={
                '_from_conflict': str(conflict_id),
                'case': ['no', 'ge', 'da', 'ac', 'in', 'pre'],
                'value': ['A', '', 'D2', '', '', ''],
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        remaining_ids = [c["id"] for c in fresh_inflection_db.get_conflicts()]
        assert conflict_id not in remaining_ids

    def test_new_word_stale_conflict_stays_blank(self, client, fresh_inflection_db):
        """A from_conflict id that no longer resolves leaves the form blank (no
        false source note)."""
        data = client.get('/debug/inflections/new?from_conflict=99999').get_data(as_text=True)
        assert 'конфликта #99999' not in data

    def test_save_as_new_dismisses_conflict(self, client, fresh_inflection_db):
        conflict_id, existing_word_id, _, word2 = self._make_split_conflict(fresh_inflection_db)
        fresh_inflection_db.delete_word(word2)  # existing word gone

        response = client.post(
            '/debug/inflections/new',
            data={'_from_conflict': str(conflict_id), 'case': ['no', 'da'], 'value': ['A', 'D2']},
            follow_redirects=False,
        )
        assert response.status_code == 302
        remaining_ids = [c["id"] for c in fresh_inflection_db.get_conflicts()]
        assert conflict_id not in remaining_ids

    def test_dismiss_conflict_form(self, client, fresh_inflection_db):
        conflict_id, _, _, _ = self._make_split_conflict(fresh_inflection_db)
        response = client.post(
            f'/debug/inflections/conflicts/{conflict_id}/dismiss',
            follow_redirects=False,
        )
        assert response.status_code == 302
        remaining_ids = [c["id"] for c in fresh_inflection_db.get_conflicts()]
        assert conflict_id not in remaining_ids


class TestConflictsPageMergeLink:
    """Conflicts page should have merge links."""

    def test_merge_link_present(self, client, fresh_inflection_db):
        fresh_inflection_db.save_word({"no": "A", "ge": "G1", "da": "D1"})
        fresh_inflection_db.save_word({"no": "B", "ge": "G2", "da": "D2"})
        fresh_inflection_db.save_word({"no": "A", "da": "D2"})  # creates conflict

        response = client.get('/debug/inflections/conflicts')
        data = response.get_data(as_text=True)
        assert 'Слить' in data or 'merge' in data.lower()

    def test_merge_link_points_to_edit_page(self, client, fresh_inflection_db):
        fresh_inflection_db.save_word({"no": "A", "ge": "G1", "da": "D1"})
        fresh_inflection_db.save_word({"no": "B", "ge": "G2", "da": "D2"})
        fresh_inflection_db.save_word({"no": "A", "da": "D2"})

        response = client.get('/debug/inflections/conflicts')
        data = response.get_data(as_text=True)
        assert '/edit?merge=' in data


class TestDictionaryPageEditLink:
    """Dictionary page should have edit links (not broken onclick)."""

    def test_edit_link_present(self, client, fresh_inflection_db):
        fresh_inflection_db.save_word({"no": "Ромашка", "ge": "Ромашки"})
        response = client.get('/debug/inflections')
        data = response.get_data(as_text=True)
        assert '/edit' in data
        assert 'onclick' not in data or 'editWord' not in data

    def test_no_broken_onclick(self, client, fresh_inflection_db):
        fresh_inflection_db.save_word({"no": "Значение", "ge": "Значения"})
        response = client.get('/debug/inflections')
        data = response.get_data(as_text=True)
        # Should not have tojson in onclick
        assert 'tojson' not in data
