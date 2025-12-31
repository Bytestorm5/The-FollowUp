---
title: Add custom items and links to the `<UserButton />` component
description: Learn how to add custom items and include external links within the
  <UserButton /> menu.
sdk: astro, chrome-extension, expo, nextjs, nuxt, react, react-router, remix,
  tanstack-react-start, vue, js-frontend
sdkScoped: "true"
canonical: /docs/:sdk:/guides/customizing-clerk/adding-items/user-button
lastUpdated: 2025-12-17T15:20:44.000Z
availableSdks: astro,chrome-extension,expo,nextjs,nuxt,react,react-router,remix,tanstack-react-start,vue,js-frontend
notAvailableSdks: android,ios,expressjs,fastify,go,ruby,js-backend
activeSdk: nextjs
sourceFile: /docs/guides/customizing-clerk/adding-items/user-button.mdx
---

The <SDKLink href="/docs/:sdk:/reference/components/user/user-button" sdks={["astro","chrome-extension","expo","nextjs","nuxt","react","react-router","remix","tanstack-react-start","vue","js-frontend"]} code={true}>\<UserButton /></SDKLink> component supports *custom* menu items, allowing the incorporation of app-specific settings or additional functionality.

There are two types of custom menu items available:

* <SDKLink href="/docs/:sdk:/guides/customizing-clerk/adding-items/user-button#user-button-action" sdks={["astro","chrome-extension","expo","nextjs","nuxt","react","react-router","remix","tanstack-react-start","vue","js-frontend"]} code={true}>\<UserButton.Action></SDKLink> - A menu item that triggers an action when clicked.
* <SDKLink href="/docs/:sdk:/guides/customizing-clerk/adding-items/user-button#user-button-link" sdks={["astro","chrome-extension","expo","nextjs","nuxt","react","react-router","remix","tanstack-react-start","vue","js-frontend"]} code={true}>\<UserButton.Link></SDKLink> - A menu item that navigates to a page when clicked.

You can also <SDKLink href="/docs/:sdk:/guides/customizing-clerk/adding-items/user-button#reorder-default-items" sdks={["astro","chrome-extension","expo","nextjs","nuxt","react","react-router","remix","tanstack-react-start","vue","js-frontend"]}>reorder default items</SDKLink> and <SDKLink href="/docs/:sdk:/guides/customizing-clerk/adding-items/user-button#conditionally-render-menu-items" sdks={["astro","chrome-extension","expo","nextjs","nuxt","react","react-router","remix","tanstack-react-start","vue","js-frontend"]}>conditionally render menu items</SDKLink>.

## `<UserButton.Action>`

`<UserButton.Action />` allows you to add actions to the `<UserButton />` component, like opening a chat or triggering a modal.

### Props

`<UserButton.Action />` accepts the following props:

<Properties>
  * `label`
  * `string`

  The name that will be displayed in the menu of the user button.

  ***

  * `labelIcon`
  * `React.ReactElement`

  An icon displayed next to the label in the menu.

  ***

  * `open?`
  * `string`

  The path segment that will be used to open the user profile modal to a specific page.

  ***

  * `onClick?`
  * `void`

  A function to be called when the menu item is clicked.
</Properties>

### Examples

#### Add an action

The following example adds an "Open chat" action to the `<UserButton />` component. When a user selects the `<UserButton />`, there will be an "Open chat" menu item.

<If notSdk={["astro", "js-frontend", "vue", "nuxt"]}>
  ```tsx
  const DotIcon = () => {
    return (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" fill="currentColor">
        <path d="M256 512A256 256 0 1 0 256 0a256 256 0 1 0 0 512z" />
      </svg>
    )
  }

  const CustomUserButton = () => {
    return (
      <header>
        <UserButton>
          <UserButton.MenuItems>
            <UserButton.Action
              label="Open chat"
              labelIcon={<DotIcon />}
              onClick={() => alert('init chat')}
            />
          </UserButton.MenuItems>
        </UserButton>
      </header>
    )
  }

  export default CustomUserButton
  ```
</If>

#### Add an action and a custom page

The following example adds an "Open help" action to the `<UserButton />` component, as well as a <SDKLink href="/docs/:sdk:/guides/customizing-clerk/adding-items/user-profile" sdks={["astro","chrome-extension","expo","nextjs","nuxt","react","react-router","remix","tanstack-react-start","vue","js-frontend"]}>custom page</SDKLink> titled "Help". When a user selects the `<UserButton />`, there will be "Open help" and "Help" menu items.

<If notSdk={["astro", "js-frontend", "vue", "nuxt"]}>
  ```tsx
  const DotIcon = () => {
    return (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" fill="currentColor">
        <path d="M256 512A256 256 0 1 0 256 0a256 256 0 1 0 0 512z" />
      </svg>
    )
  }

  const CustomUserButton = () => {
    return (
      <header>
        <UserButton>
          <UserButton.MenuItems>
            <UserButton.Action label="Open help" labelIcon={<DotIcon />} open="help" />
          </UserButton.MenuItems>

          <UserButton.UserProfilePage label="Help" labelIcon={<DotIcon />} url="help">
            <div>
              <h1>Help Page</h1>
              <p>This is the custom help page</p>
            </div>
          </UserButton.UserProfilePage>
        </UserButton>
      </header>
    )
  }

  export default CustomUserButton
  ```
</If>

## `<UserButton.Link>`

`<UserButton.Link />` allows you to add links to the `<UserButton />` component, like custom pages or external URLs.

### Props

`<UserButton.Link />` accept the following props, all of which are **required**:

<Properties>
  * `label`
  * `string`

  The name that will be displayed in the menu of the user button.

  ***

  * `labelIcon`
  * `React.ReactElement`

  An icon displayed next to the label in the menu.

  ***

  * `href`
  * `string`

  The path segment that will be used to navigate to the custom page.
</Properties>

### Example

The following example adds a "Create organization" link to the `<UserButton />` component. When a user selects the `<UserButton />`, there will be a "Create organization" menu item.

<If notSdk={["astro", "js-frontend", "vue", "nuxt"]}>
  ```tsx
  const DotIcon = () => {
    return (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" fill="currentColor">
        <path d="M256 512A256 256 0 1 0 256 0a256 256 0 1 0 0 512z" />
      </svg>
    )
  }

  const CustomUserButton = () => {
    return (
      <header>
        <UserButton>
          <UserButton.MenuItems>
            <UserButton.Link
              label="Create organization"
              labelIcon={<DotIcon />}
              href="/create-organization"
            />
          </UserButton.MenuItems>
        </UserButton>
      </header>
    )
  }

  export default CustomUserButton
  ```
</If>

## Reorder default items

The `<UserButton />` component includes two default menu items: `Manage account` and `Sign out`, in that order. You can reorder these default items by setting the `label` prop to `'manageAccount'` or `'signOut'`. This will target the existing default item and allow you to rearrange it.

In the following example, the "Sign out" menu item is moved to the top of the menu, a custom "Create organization" link is added as the second menu item, and the "Manage account" menu item is moved to the bottom of the menu.

<If notSdk={["astro", "js-frontend", "vue", "nuxt"]}>
  ```tsx
  const DotIcon = () => {
    return (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" fill="currentColor">
        <path d="M256 512A256 256 0 1 0 256 0a256 256 0 1 0 0 512z" />
      </svg>
    )
  }

  const CustomUserButton = () => {
    return (
      <header>
        <UserButton>
          <UserButton.MenuItems>
            <UserButton.Action label="signOut" />
            <UserButton.Link
              label="Create organization"
              labelIcon={<DotIcon />}
              href="/create-organization"
            />
            <UserButton.Action label="manageAccount" />
          </UserButton.MenuItems>
        </UserButton>
      </header>
    )
  }

  export default CustomUserButton
  ```
</If>

## Conditionally render menu items

<If notSdk="js-frontend">
  To conditionally render menu items based on a user's Role or Custom Permissions, you can use the <SDKLink href="/docs/reference/backend/types/auth-object#has" sdks={["js-backend"]} code={true}>has()</SDKLink> helper function.
</If>

In the following example, the "Create organization" menu item will only render if the current user has the `org:app:admin` permission.

<If notSdk={["astro", "js-frontend", "vue", "nuxt"]}>
  ```tsx
  const DotIcon = () => {
    return (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" fill="currentColor">
        <path d="M256 512A256 256 0 1 0 256 0a256 256 0 1 0 0 512z" />
      </svg>
    )
  }

  const CustomUserButton = () => {
    const { has, isLoaded } = useAuth()

    if (!isLoaded) {
      return <span>Loading...</span>
    }

    const isAdmin = has({ permission: 'org:app:admin' })

    return (
      <header>
        <UserButton>
          {isAdmin && (
            <UserButton.MenuItems>
              <UserButton.Link
                label="Create organization"
                labelIcon={<DotIcon />}
                href="/create-organization"
              />
            </UserButton.MenuItems>
          )}
        </UserButton>
      </header>
    )
  }

  export default CustomUserButton
  ```
</If>
