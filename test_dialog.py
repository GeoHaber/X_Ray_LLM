import flet as ft


def main(page: ft.Page):
    page.title = "Dialog Test"

    def on_click(e):
        dlg = ft.AlertDialog(
            title=ft.Text("Hello Dialog"),
            content=ft.Text("This is a test."),
            actions=[ft.TextButton("Close", on_click=lambda e: page.pop_dialog())],
        )
        page.show_dialog(dlg)

    page.add(ft.ElevatedButton("Open Dialog", on_click=on_click))


ft.app(target=main)
